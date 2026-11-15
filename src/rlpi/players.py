"""Espace joueur (version multi-joueurs) : rassembler les parties d'un joueur et calculer son tableau de bord.

Les parties d'un joueur sont toutes celles où figure son identifiant (table Postgres match_players), quels que
soient ses coéquipiers et celui qui a envoyé le replay. Leur traitement est dans le stockage S3 : games/<partie>/…

Ce module, utilisé par le serveur du tableau de bord (rlpi.serve) :
    1. télécharge les parties manquantes dans un cache local partagé (<cache>/games/<partie>/) ;
    2. les rassemble (rlpi.game merge) dans <cache>/players/<joueur>/data, source « perso », à côté de liens vers
       les données de référence (RLCS, SSL, rapports des modèles) du dossier de données principal ;
    3. calcule la synergie du joueur, puis le contenu du tableau de bord, dans un processus séparé où
       RLPI_DATA pointe sur ce dossier (le code du tableau de bord reste inchangé).

    python -m rlpi.players sync --player Steam:7656…     # rassembler (test, en ligne de commande)

Variables : DATABASE_URL, S3_* (comme le worker), RLPI_USERS_CACHE (défaut : <données>/users).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from rlpi import store

USER_SOURCE = "perso"  # nom de la source dans le dossier de données d'un joueur
MIN_GAMES_TOGETHER = 5  # coéquipier comparé : au moins 5 parties ensemble
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def enabled() -> bool:
    """Le mode multi-joueurs est actif si la base et le stockage sont configurés."""
    return bool(os.getenv("S3_ENDPOINT", "").strip() and os.getenv("DATABASE_URL", "").strip())


def cache_root() -> Path:
    from rlpi.config import DATA

    return Path(os.getenv("RLPI_USERS_CACHE") or DATA / "users")


def lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


# --------------------------------------------------------------------------------------------------------------
# 1. Parties du joueur


def player_matches(player_id: str) -> dict[str, str]:
    """{partie: date de dernière mise à jour} des parties traitées où figure le joueur."""
    with store.db() as c:
        rows = c.execute("SELECT m.id, m.updated_at FROM match_players mp JOIN matches m ON m.id = mp.match_id "
                         "WHERE mp.player_id = %s AND m.status IN ('ok', 'partiel')", (player_id,)).fetchall()
    return {mid: upd.isoformat() for mid, upd in rows}


def fetch_game(cli, b: str, mid: str, version: str) -> Path:
    """Télécharge games/<partie>/ dans le cache partagé si absent ou retraité depuis."""
    dest = cache_root() / "games" / store.safe(mid)
    stamp = dest / ".version"
    if stamp.exists() and stamp.read_text(encoding="utf-8") == version:
        return dest
    with lock("game:" + mid):
        shutil.rmtree(dest, ignore_errors=True)
        prefix = f"games/{mid}/"
        for page in cli.get_paginator("list_objects_v2").paginate(Bucket=b, Prefix=prefix):
            for o in page.get("Contents", []):
                f = dest / o["Key"][len(prefix):]
                f.parent.mkdir(parents=True, exist_ok=True)
                cli.download_file(b, o["Key"], str(f))
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(version, encoding="utf-8")
    return dest


# --------------------------------------------------------------------------------------------------------------
# 2. Dossier de données du joueur


def _link(src: Path, dst: Path) -> None:
    """Lien vers un fichier ou dossier de référence (lien symbolique ; sinon liens physiques ou copie)."""
    if dst.exists() or dst.is_symlink():
        return
    try:
        os.symlink(src, dst, target_is_directory=src.is_dir())
    except OSError:  # Windows sans droit de créer des liens symboliques
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                _link(f, dst / f.name)
        else:
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)


def link_reference(data: Path, ref: Path, own_sources: set[str]) -> None:
    """Relie les données de référence (tout ce qui n'est pas une source « joueur ») dans le dossier du joueur."""
    def own(name: str) -> bool:
        stem = name.split(".")[0]
        return name in own_sources or any(stem.endswith(f"_{s}") for s in own_sources)

    (data / "features").mkdir(parents=True, exist_ok=True)
    (data / "frames").mkdir(parents=True, exist_ok=True)
    for f in (ref / "features").iterdir():
        if not own(f.name):
            _link(f, data / "features" / f.name)
    for f in (ref / "frames").iterdir():
        if not own(f.name):
            _link(f, data / "frames" / f.name)


def build(player_id: str, force: bool = False) -> tuple[Path | None, int]:
    """Rassemble les parties du joueur. Retourne (son dossier de données ou None, nombre de parties)."""
    from rlpi import config, game

    matches = player_matches(player_id)
    if not matches:
        return None, 0
    root = cache_root() / "players" / store.safe(player_id)
    data = root / "data"
    manifest_f = root / "manifest.json"
    with lock("player:" + player_id):
        old = json.loads(manifest_f.read_text(encoding="utf-8")) if manifest_f.exists() else None
        ok = (data / "features" / f"player_match_stats_{USER_SOURCE}.parquet").exists()
        if old == matches and ok and not force:
            return data, len(matches)
        cli, b = store.s3(), store.bucket()
        dirs = [fetch_game(cli, b, mid, ver) for mid, ver in sorted(matches.items())]
        # On repart d'un dossier propre : les tables du joueur sont entièrement reconstruites
        shutil.rmtree(data, ignore_errors=True)
        data.mkdir(parents=True)
        game.merge(dirs, data, USER_SOURCE)
        link_reference(data, config.DATA, {USER_SOURCE, config.SOURCE, "theo", "perso", "users"})
        _run(player_id, data, ["synergy"])
        manifest_f.write_text(json.dumps(matches), encoding="utf-8")
    return data, len(matches)


# --------------------------------------------------------------------------------------------------------------
# 3. Tableau de bord


def _env(data: Path) -> dict:
    from rlpi.config import MODELS

    src = Path(__file__).resolve().parents[1]
    e = os.environ | {"RLPI_DATA": str(data), "RLPI_SOURCE": USER_SOURCE, "RLPI_MODELS": str(MODELS),
                      "RLPI_USERS_CACHE": str(cache_root()), "PYTHONIOENCODING": "utf-8"}
    e["PYTHONPATH"] = os.pathsep.join([str(src), e.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    return e


def _run(player_id: str, data: Path, args: list[str]) -> str:
    p = subprocess.run([sys.executable, "-m", "rlpi.players", "_inner", "--player", player_id, *args],
                       env=_env(data), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=600)
    if p.returncode != 0:
        raise RuntimeError(f"rlpi.players {args[0]} ({player_id}) : {(p.stderr or p.stdout)[-1500:]}")
    return p.stdout


def payload(player_id: str, data: Path, j: str | None, since: str | None, until: str | None,
            avec: list[str], sans: list[str]) -> dict:
    """Contenu du tableau de bord du joueur (même structure que dans rlpi.serve) ; `data` vient de build()."""
    args = ["payload"] + (["--j", j] if j else []) + (["--since", since] if since else []) \
        + (["--until", until] if until else []) + (["--avec", ",".join(avec)] if avec else []) \
        + (["--sans", ",".join(sans)] if sans else [])
    out = _run(player_id, data, args)
    return json.loads(out.strip().splitlines()[-1])


def _profile_ids(me: str) -> tuple[list[str], dict[str, str], list[dict]]:
    """Exécuté dans le processus fils : le joueur et ses coéquipiers les plus fréquents (2 au plus)."""
    import polars as pl

    from rlpi.config import FEATURES

    st = pl.read_parquet(FEATURES / f"player_match_stats_{USER_SOURCE}.parquet",
                         columns=["player_id", "player_name", "date", "replay_file", "team"])
    mine = st.filter(pl.col("player_id") == me).select("replay_file", "team")
    mates = st.join(mine, on=["replay_file", "team"]).filter(pl.col("player_id") != me)
    top = (mates.group_by("player_id").agg(pl.len().alias("n")).filter(pl.col("n") >= MIN_GAMES_TOGETHER)
           .sort("n", descending=True))
    ids = [me, *top["player_id"].head(2).to_list()]
    names = {pid: st.filter(pl.col("player_id") == pid).sort("date")["player_name"][-1] for pid in ids}
    days = (st.filter(pl.col("player_id") == me).unique("replay_file")
            .with_columns(pl.col("date").str.slice(0, 10).alias("d")).group_by("d").agg(pl.len().alias("n"))
            .sort("d").to_dicts())
    return ids, names, days


def _inner(a: argparse.Namespace) -> None:
    """Exécuté dans le processus fils (RLPI_DATA = dossier du joueur)."""
    from rlpi.config import SOURCE

    assert SOURCE == USER_SOURCE
    if a.cmd2 == "synergy":
        from rlpi import synergy

        synergy.run(SOURCE, None)
        return
    from rlpi.dashboard import make_payload

    ids, names, days = _profile_ids(a.player)
    sel = a.j if a.j in ids else ids[0]
    avec = [x for x in (a.avec or "").split(",") if x in ids and x != sel]
    sans = [x for x in (a.sans or "").split(",") if x in ids and x != sel and x not in avec]
    try:
        pay, err = make_payload(sel, [i for i in ids if i != sel], a.since, a.until, avec, sans), None
    except SystemExit as e:  # aucune partie pour ce filtre
        pay, err = None, str(e)
    out = {"dynamic": True, "default": sel, "order": ids, "names": names, "days": days,
           "filters": {"j": sel, "du": a.since, "au": a.until, "avec": avec, "sans": sans},
           "profiles": {sel: pay} if pay else {}, "error": err}
    sys.stdout.flush()
    print(json.dumps(out, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser(description="Espace joueur")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--player", required=True)
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("_inner")
    s.add_argument("--player", required=True)
    s.add_argument("cmd2", choices=["synergy", "payload"])
    for k in ("--j", "--since", "--until", "--avec", "--sans"):
        s.add_argument(k)
    a = ap.parse_args()
    if a.cmd == "_inner":
        _inner(a)
    else:
        data, n = build(a.player, a.force)
        print(f"{n} partie(s) → {data}")


if __name__ == "__main__":
    main()
