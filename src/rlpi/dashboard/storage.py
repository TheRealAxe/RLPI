"""Agrégats du tableau de bord dans Postgres (tables créées par migrations/V5__agregats.sql).

write(conn, agrégat)          worker : enregistre les agrégats d'une partie, augmente la version de ses joueurs
player_games(joueur)          serveur : parties agrégées du joueur (Games), gardées en mémoire par version
reference()                   serveur : partie fixe, recalculée si ses fichiers ont changé (empreinte)
missing(conn)                 parties traitées sans agrégats à jour (à recalculer par le worker)
compute_match(…)              télécharge games/<partie>/ et calcule ses agrégats (reprise, reconstruction)
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rlpi import logs
from rlpi.dashboard.aggregate import VALUE_COLUMNS, VERSION
from rlpi.dashboard.common import decode, encode

if TYPE_CHECKING:
    import psycopg

    from rlpi.context import DataContext
    from rlpi.dashboard.content import Games

OK_STATUSES = ("ok", "partiel")
REFERENCE_NAME = "tableau_de_bord"
# colonne en base ← clé de « cols » (rlpi.dashboard.aggregate)
COLUMNS = {
    "player_name": "player_name",
    "team": "team",
    "in_stats": "in_stats",
    "is_bot": "is_bot",
    "played": "date",
    "won": "won",
    "team_goals": "team_goals",
    "opp_goals": "opp_goals",
    **{k: k for k in VALUE_COLUMNS},
}


def _json(x: Any):
    from psycopg.types.json import Jsonb

    return Jsonb(encode(x), dumps=lambda o: json.dumps(o, ensure_ascii=False, allow_nan=False))


# ------------------------------------------------------------------------------------------------ écriture


def write(conn: psycopg.Connection, agg: dict) -> None:
    """Remplace les agrégats de la partie (une transaction) et augmente la version des données de ses joueurs."""
    from psycopg import sql

    mid = agg["match_id"]
    cols = list(COLUMNS)
    insert = sql.SQL("INSERT INTO player_game_aggregates (match_id, player_id, {}, data, details) VALUES ({})").format(
        sql.SQL(", ").join(map(sql.Identifier, cols)), sql.SQL(", ").join(sql.Placeholder() * (len(cols) + 4))
    )
    with conn.transaction():
        conn.execute("DELETE FROM game_aggregates WHERE match_id = %s", (mid,))  # lignes des joueurs en cascade
        conn.execute(
            "INSERT INTO game_aggregates (match_id, version, replay, data) VALUES (%s, %s, %s, %s)",
            (mid, agg["version"], agg["replay"], _json(agg["game"])),
        )
        with conn.cursor() as cur:
            cur.executemany(
                insert,
                [
                    (mid, pid, *[p["cols"].get(COLUMNS[c]) for c in cols], _json(p["data"]), _json(p["details"]))
                    for pid, p in agg["players"].items()
                ],
            )
        conn.execute(
            "INSERT INTO player_versions (player_id, version) SELECT unnest(%s::text[]), 1 "
            "ON CONFLICT (player_id) DO UPDATE SET version = player_versions.version + 1, updated_at = now()",
            (sorted(agg["players"]),),
        )


def missing(conn: psycopg.Connection, everything: bool = False, skip_dead: bool = False) -> list[str]:
    """Parties traitées dont les agrégats manquent ou sont d'une version de calcul ancienne (toutes si everything).
    skip_dead : sans celles dont le calcul de la version courante attend en lettre morte (rattrapage périodique :
    pas d'échec répété ; une nouvelle VERSION les reprend, elle corrige peut-être ce qui avait échoué)."""
    rows = conn.execute(
        "SELECT m.id FROM matches m LEFT JOIN game_aggregates g ON g.match_id = m.id "
        "WHERE m.status IN ('ok', 'partiel') AND (%s OR g.match_id IS NULL OR g.version <> %s) "
        "AND NOT (%s AND EXISTS (SELECT 1 FROM dead_tasks d WHERE d.kind = 'aggregate' AND d.ref = m.id "
        "AND d.version = %s AND d.retried_at IS NULL)) ORDER BY m.id",
        (everything, VERSION, skip_dead, VERSION),
    ).fetchall()
    return [r[0] for r in rows]


def is_current(conn: psycopg.Connection, match_id: str) -> bool:
    row = conn.execute("SELECT version FROM game_aggregates WHERE match_id = %s", (match_id,)).fetchone()
    return row is not None and row[0] == VERSION


def s3_parallel() -> int:
    """Fichiers téléchargés en même temps depuis Garage pour une partie (RLPI_S3_PARALLEL, défaut 8)."""
    v = os.getenv("RLPI_S3_PARALLEL", "").strip()
    return max(1, int(v)) if v.isdigit() else 8


def download_game(cli: Any, bucket: str, match_id: str, dest: Path, parallel: int | None = None) -> Path:
    """Télécharge games/<partie>/ (sortie du worker) dans dest, `parallel` fichiers à la fois (client boto3 partagé
    entre les fils : il le permet)."""
    prefix = f"games/{match_id}/"
    keys = [
        o["Key"]
        for page in cli.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
        for o in page.get("Contents", [])
    ]
    if not keys:
        raise FileNotFoundError(f"rien dans le stockage sous {prefix}")

    def one(key: str) -> None:
        f = dest / key[len(prefix) :]
        f.parent.mkdir(parents=True, exist_ok=True)
        cli.download_file(bucket, key, str(f))

    n = min(parallel or s3_parallel(), len(keys))
    if n <= 1:
        for k in keys:
            one(k)
    else:
        with ThreadPoolExecutor(max_workers=n, thread_name_prefix="garage") as ex:
            list(ex.map(one, keys))
    return dest


def compute_from_storage(cli: Any, bucket: str, match_id: str) -> dict:
    """Agrégats d'une partie déjà traitée, calculés à partir de ses fichiers dans le stockage (sans les écrire)."""
    from rlpi.dashboard.aggregate import compute, from_game_dir

    tmp = Path(tempfile.mkdtemp(prefix="rlpi_agg_"))
    try:
        return compute(from_game_dir(download_game(cli, bucket, match_id, tmp / "partie"), match_id))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def compute_match(conn: psycopg.Connection, cli: Any, bucket: str, match_id: str) -> dict:
    """Agrégats d'une partie déjà traitée, à partir de ses fichiers dans le stockage ; enregistrés en base."""
    agg = compute_from_storage(cli, bucket, match_id)
    write(conn, agg)
    return agg


def rebuild(
    conn: psycopg.Connection,
    cli: Any,
    bucket: str,
    match_ids: list[str],
    parallel: int = 3,
    on_done: Callable[[int, str, Exception | None], None] | None = None,
) -> int:
    """Reconstruction : `parallel` parties téléchargées et calculées à la fois (fils), écrites une par une dans ce
    fil (une connexion Postgres ne se partage pas). Retourne le nombre de parties réussies ; `on_done(k, partie,
    erreur)` après chacune."""
    ok = 0
    with ThreadPoolExecutor(max_workers=max(1, parallel), thread_name_prefix="rebuild") as ex:
        futures = {ex.submit(compute_from_storage, cli, bucket, mid): mid for mid in match_ids}
        for k, fut in enumerate(as_completed(futures), 1):
            mid, err = futures[fut], None
            try:
                write(conn, fut.result())
                ok += 1
            except Exception as e:  # noqa: BLE001 — une partie en échec n'arrête pas la reconstruction
                err = e
            if on_done:
                on_done(k, mid, err)
    return ok


# ------------------------------------------------------------------------------------------------ lecture


def player_state(conn: psycopg.Connection, player_id: str) -> tuple[int, int, int]:
    """(version des données du joueur, parties agrégées à jour, parties traitées sans agrégats à jour)."""
    row = conn.execute(
        "SELECT count(*) FILTER (WHERE g.version = %s), count(*) FILTER (WHERE g.version IS DISTINCT FROM %s), "
        "(SELECT version FROM player_versions WHERE player_id = %s) "
        "FROM match_players mp JOIN matches m ON m.id = mp.match_id "
        "LEFT JOIN game_aggregates g ON g.match_id = m.id "
        "WHERE mp.player_id = %s AND m.status IN ('ok', 'partiel')",
        (VERSION, VERSION, player_id, player_id),
    ).fetchone()
    assert row is not None
    return int(row[2] or 0), int(row[0]), int(row[1])


def load_games(conn: psycopg.Connection, player_id: str) -> Games:
    """Agrégats à jour des parties du joueur ; les détails des joueurs ne sont lus qu'à la demande."""
    from rlpi import store
    from rlpi.dashboard.content import Games

    games = conn.execute(
        "SELECT g.match_id, g.replay, g.data FROM match_players mp JOIN matches m ON m.id = mp.match_id "
        "JOIN game_aggregates g ON g.match_id = m.id AND g.version = %s "
        "WHERE mp.player_id = %s AND m.status IN ('ok', 'partiel')",
        (VERSION, player_id),
    ).fetchall()
    ids = [g[0] for g in games]
    aggs = {
        mid: {"match_id": mid, "replay": replay, "version": VERSION, "game": decode(data), "players": {}}
        for mid, replay, data in games
    }
    cols = list(COLUMNS)
    from psycopg import sql

    q = sql.SQL("SELECT match_id, player_id, {}, data FROM player_game_aggregates WHERE match_id = ANY(%s)").format(
        sql.SQL(", ").join(map(sql.Identifier, cols))
    )
    for row in conn.execute(q, (ids,)).fetchall():
        mid, pid, *vals, data = row
        aggs[mid]["players"][pid] = {
            "cols": {COLUMNS[c]: v for c, v in zip(cols, vals)},
            "data": decode(data),
            "details": None,
        }

    def details(pid: str) -> dict[str, dict]:
        with store.db() as c:
            return {
                mid: decode(d)
                for mid, d in c.execute(
                    "SELECT match_id, details FROM player_game_aggregates WHERE player_id = %s AND match_id = ANY(%s)",
                    (pid, ids),
                ).fetchall()
            }

    return Games(aggs.values(), details)


_cache: OrderedDict[str, tuple[int, int, Games]] = OrderedDict()
_cache_lock = threading.Lock()
CACHE_MAX = 16


def player_games(player_id: str) -> tuple[Games | None, int, int]:
    """(parties du joueur ou None s'il n'en a aucune d'agrégée, nombre de parties, nombre en préparation).
    Gardées en mémoire tant que la version des données du joueur ne change pas."""
    from rlpi import store

    with store.db() as c:
        version, n, pending = player_state(c, player_id)
        if not n:
            return None, 0, pending
        with _cache_lock:
            hit = _cache.get(player_id)
            if hit and hit[:2] == (version, n):
                _cache.move_to_end(player_id)
                return hit[2], n, pending
        games = load_games(c, player_id)
        games.version = version
    with _cache_lock:
        _cache[player_id] = (version, n, games)
        _cache.move_to_end(player_id)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)
    return games, len(games), pending


# ------------------------------------------------------------------------------------------------ référence

_ref: tuple[str, dict] | None = None
_ref_lock = threading.Lock()


def ensure_reference(ctx: DataContext, force: bool = False) -> dict:
    """Référence à jour : relue en base si l'empreinte de ses fichiers n'a pas changé, sinon recalculée (un seul
    processus à la fois, verrou Postgres) et enregistrée."""
    global _ref
    from rlpi import store
    from rlpi.dashboard import reference

    fp = reference.fingerprint(ctx)
    with _ref_lock:
        if _ref is not None and _ref[0] == fp and not force:
            return _ref[1]
        with store.db() as c:
            row = c.execute(
                "SELECT data FROM reference_aggregates WHERE name = %s AND fingerprint = %s", (REFERENCE_NAME, fp)
            ).fetchone()
            if row is None or force:
                with c.transaction():
                    c.execute("SELECT pg_advisory_xact_lock(hashtext('rlpi:reference'))")
                    row = (
                        None
                        if force
                        else c.execute(
                            "SELECT data FROM reference_aggregates WHERE name = %s AND fingerprint = %s",
                            (REFERENCE_NAME, fp),
                        ).fetchone()
                    )
                    if row is None:
                        data = reference.build(ctx)
                        c.execute(
                            "INSERT INTO reference_aggregates (name, fingerprint, data) VALUES (%s, %s, %s) "
                            "ON CONFLICT (name) DO UPDATE SET fingerprint = EXCLUDED.fingerprint, "
                            "data = EXCLUDED.data, computed_at = now()",
                            (REFERENCE_NAME, fp, _json(data)),
                        )
                        logs.log(f"référence du tableau de bord recalculée ({fp[:10]})")
                        data = decode(json.loads(json.dumps(encode(data))))  # même forme que relue en base
                        _ref = (fp, data)
                        return data
            data = decode(row[0])
        _ref = (fp, data)
        return data


def reference_context() -> DataContext:
    """Dossiers de la référence sur le serveur : RLPI_DATA (features/, frames/rlcs/) et RLPI_MODELS."""
    from rlpi import config
    from rlpi.context import DataContext

    return DataContext(data=config.DATA, source=config.SOURCE, ref=config.DATA, models=config.MODELS)


_ref_checked = 0.0
REF_CHECK_S = 60  # empreinte des fichiers de la référence vérifiée au plus une fois par minute


def reference_fingerprint() -> str:
    """Empreinte de la référence en mémoire (clé du cache des pages)."""
    return _ref[0] if _ref else ""


def reference() -> dict:
    global _ref_checked
    import time

    if _ref is not None and time.monotonic() - _ref_checked < REF_CHECK_S:
        return _ref[1]
    data = ensure_reference(reference_context())
    _ref_checked = time.monotonic()
    return data
