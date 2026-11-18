"""« Nouveau match traité » : messages Redis du worker vers le navigateur du joueur (Server-Sent Events).

Une fois les agrégats d'une partie écrits (rlpi.dashboard.storage.write), le worker publie sur le canal de chaque
joueur inscrit de la partie (`rlpi:evenements:<joueur>`) : {"match": <id>, "parties": <nombre de parties prêtes>}.
L'API (GET /api/moi/evenements) relaie ces messages au navigateur du joueur connecté. Aucun calcul ni lecture en base
à chaque message côté API ; côté worker, une seule requête par partie.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg
    import redis

PREFIX = "rlpi:evenements:"


def channel(player_id: str) -> str:
    return PREFIX + player_id


def ready_counts(conn: psycopg.Connection, players: list[str]) -> dict[str, int]:
    """Parties prêtes (agrégats à jour) de chacun des joueurs inscrits parmi `players`."""
    from rlpi.dashboard.aggregate import VERSION

    rows = conn.execute(
        "SELECT mp.player_id, count(*) FROM match_players mp JOIN matches m ON m.id = mp.match_id "
        "JOIN game_aggregates g ON g.match_id = m.id AND g.version = %s "
        "WHERE mp.player_id = ANY(%s) AND m.status IN ('ok', 'partiel') "
        "AND EXISTS (SELECT 1 FROM accounts a WHERE a.player_id = mp.player_id) GROUP BY mp.player_id",
        (VERSION, players),
    ).fetchall()
    return {pid: int(n) for pid, n in rows}


def publish_match(r: redis.Redis, conn: psycopg.Connection, match_id: str, players: list[str]) -> int:
    """Annonce la partie à ses joueurs inscrits ; retourne le nombre de messages publiés."""
    n = 0
    for pid, count in ready_counts(conn, players).items():
        r.publish(channel(pid), json.dumps({"match": match_id, "parties": count}))
        n += 1
    return n
