"""Ralentis des touches les plus coûteuses (« Revoir » dans « À travailler »), en base (table clips, V9).

1. L'API (POST /api/clips) note la demande : une ligne « en_attente » pour (partie, joueur, touche), et une tâche
   {"type": "clip", "match": id, "player": id} dans la file Redis. Seules les parties où joue le joueur connecté
   sont acceptées, et seulement ses propres touches.
2. Un worker télécharge la partie analysée et son replay brut, découpe le ralenti de chaque touche demandée au
   format du player 3D (rlpi.pov : 30 images/s, saut / dodge, réglages caméra du joueur) et, au passage, ceux des
   autres touches les plus coûteuses du joueur dans cette partie (les clics suivants sont immédiats).
   Un ralenti d'un format plus ancien (pov.FORMAT) est considéré comme absent : il est refait à la demande.
3. L'interface interroge GET /api/clips/{partie}/{image} jusqu'à ce que le ralenti soit prêt.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rlpi.pov import FORMAT

if TYPE_CHECKING:
    import psycopg

BEFORE_S, AFTER_S = 4.0, 2.0  # secondes montrées avant et après la touche
N_PREFETCH = 10  # touches les plus coûteuses du joueur découpées en même temps (comme « Les actions qui coûtent »)
RETRY_AFTER_MIN = 15  # une demande restée « en_attente » plus longtemps (worker perdu) peut être relancée


def plays_in(conn: psycopg.Connection, player: str, match_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM match_players mp JOIN matches m ON m.id = mp.match_id "
        "WHERE mp.match_id = %s AND mp.player_id = %s AND m.status IN ('ok', 'partiel') AND m.replay_key IS NOT NULL",
        (match_id, player),
    ).fetchone()
    return row is not None


def get(conn: psycopg.Connection, player: str, match_id: str, i: int) -> dict:
    """État du ralenti : {"statut": aucun | en_attente | pret | erreur, "erreur", "clip"}."""
    row = conn.execute(
        "SELECT status, error, clip FROM clips WHERE match_id = %s AND player_id = %s AND i = %s", (match_id, player, i)
    ).fetchone()
    if row is None:
        return {"statut": "aucun", "erreur": None, "clip": None}
    status, error, clip = row
    if status == "pret" and (clip or {}).get("format") != FORMAT:
        return {"statut": "aucun", "erreur": None, "clip": None}  # ancien format : à refaire
    return {"statut": status, "erreur": error, "clip": clip if status == "pret" else None}


def request(conn: psycopg.Connection, player: str, match_id: str, i: int) -> tuple[str, bool]:
    """Note la demande. Retourne (statut, à mettre en file ?) : rien à faire si le ralenti est prêt ou déjà en
    préparation depuis peu ; une erreur ou une demande trop ancienne est relancée."""
    row = conn.execute(
        "INSERT INTO clips (match_id, player_id, i) VALUES (%s, %s, %s) "
        "ON CONFLICT (match_id, player_id, i) DO UPDATE SET status = 'en_attente', error = NULL, created_at = now() "
        "WHERE clips.status = 'erreur' OR (clips.status = 'en_attente' "
        "AND clips.created_at < now() - make_interval(mins => %s)) "
        "OR (clips.status = 'pret' AND clips.clip->>'format' IS DISTINCT FROM %s) "
        "RETURNING status",
        (match_id, player, i, RETRY_AFTER_MIN, str(FORMAT)),
    ).fetchone()
    if row is not None:  # nouvelle demande ou relance
        return "en_attente", True
    cur = conn.execute(
        "SELECT status FROM clips WHERE match_id = %s AND player_id = %s AND i = %s", (match_id, player, i)
    ).fetchone()
    return (cur[0] if cur else "en_attente"), False


# ------------------------------------------------------------------------------------------------ worker


def picks(touch_values: Any, player: str, wanted: list[int], n_prefetch: int = N_PREFETCH) -> list[dict]:
    """Touches à découper : celles demandées puis les plus coûteuses du joueur dans la partie (sans doublon)."""
    import polars as pl

    me = touch_values.filter(pl.col("player_id") == player)
    rows = {int(r["i"]): r for r in me.select("replay", "i", "player_id", "action", "dv").iter_rows(named=True)}
    order = [i for i in wanted if i in rows]
    order += [int(i) for i in me.sort("dv").head(n_prefetch)["i"].to_list() if int(i) not in order]
    return [{**rows[i], "origin": "perso"} for i in order]


def build(
    conn: psycopg.Connection,
    cli: Any,
    bucket: str,
    match_id: str,
    player: str,
    log: Callable[[str], None] = print,
) -> int:
    """Worker : découpe les ralentis en attente du joueur pour cette partie (et ses autres touches les plus
    coûteuses). Retourne le nombre de ralentis prêts."""
    import polars as pl
    from psycopg.types.json import Jsonb

    from rlpi import pov
    from rlpi.dashboard.storage import download_game
    from rlpi.game import GAME_SOURCE

    wanted = [
        int(r[0])
        for r in conn.execute(
            "SELECT i FROM clips WHERE match_id = %s AND player_id = %s AND status = 'en_attente'", (match_id, player)
        ).fetchall()
    ]
    if not wanted:
        return 0
    row = conn.execute("SELECT replay_key FROM matches WHERE id = %s", (match_id,)).fetchone()
    tmp = Path(tempfile.mkdtemp(prefix="rlpi_clip_"))
    try:
        if row is None or not row[0]:
            raise RuntimeError("replay brut absent du stockage")
        d = download_game(cli, bucket, match_id, tmp / "partie")
        raw = tmp / f"{match_id}.replay"
        cli.download_file(bucket, row[0], str(raw))
        tv = pl.read_parquet(d / "features" / f"touch_values_{GAME_SOURCE}.parquet")
        todo = picks(tv, player, wanted)
        made: dict[int, dict] = {}
        if todo:
            fd = d / "frames" / GAME_SOURCE
            replay = todo[0]["replay"]
            meta = json.loads((fd / f"{replay}.meta.json").read_text(encoding="utf-8"))
            ball10 = pl.read_parquet(fd / f"{replay}.parquet", columns=["ball_x", "ball_y", "ball_z"]).to_numpy()
            for i, clip in pov.extract(raw, meta, ball10, player, [p["i"] for p in todo], BEFORE_S, AFTER_S).items():
                made[i] = clip | {"id": f"{match_id}:{i}"}
        for i, clip in made.items():
            conn.execute(
                "INSERT INTO clips (match_id, player_id, i, status, clip, ready_at) VALUES (%s, %s, %s, 'pret', %s, now()) "
                "ON CONFLICT (match_id, player_id, i) DO UPDATE SET status = 'pret', clip = EXCLUDED.clip, "
                "error = NULL, ready_at = now()",
                (match_id, player, i, Jsonb(clip)),
            )
        for i in wanted:
            if i not in made:
                conn.execute(
                    "UPDATE clips SET status = 'erreur', error = %s WHERE match_id = %s AND player_id = %s AND i = %s",
                    (
                        "touche introuvable dans le replay (trop près du début ou de la fin, ou image inconnue)",
                        match_id,
                        player,
                        i,
                    ),
                )
        return len(made)
    except Exception as e:
        conn.execute(
            "UPDATE clips SET status = 'erreur', error = %s WHERE match_id = %s AND player_id = %s "
            "AND status = 'en_attente'",
            (f"{type(e).__name__}: {e}"[:500], match_id, player),
        )
        log(f"  ralentis {match_id} : échec ({type(e).__name__}: {e})"[:300])
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
