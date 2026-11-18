"""Swipe en ligne : paquets de cartes à juger à l'aveugle, en base (tables swipe_decks, swipe_judgments, V6).

1. L'API (POST /api/swipe/deck) crée le paquet : tire les cartes SSL / RLCS dans le lot fixe du volume de données
   (<RLPI_DATA>/swipe/reference_cards.json, fabriqué par `python -m rlpi.swipe pool`), les enregistre avec le
   statut « en_attente » et met une tâche {"type": "swipe", "deck": id} dans la file Redis.
2. Un worker (subtr-actor et accès au stockage) télécharge quelques parties du joueur et leurs replays bruts, tire
   les cartes du joueur, de ses coéquipiers et des lobbies (rlpi.swipe.player_cards), mélange le tout et passe le
   paquet à « pret ».
3. L'API sert les cartes sans leur origine ni leur identifiant d'origine (jugement à l'aveugle) et enregistre
   chaque jugement avec l'origine de la carte, relue en base.
"""

from __future__ import annotations

import json
import random
import shutil
import tempfile
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import psycopg

N_CARDS = 40
MIX = {"perso": 0.4, "peer": 0.15, "lobby": 0.15, "ssl": 0.15, "rlcs": 0.15}
N_GAMES = 8  # parties du joueur téléchargées par paquet
MIN_GAMES_TOGETHER = 5  # coéquipier suivi : au moins 5 parties dans la même équipe
VERDICTS = ("bien", "pas_bien", "?")
HIDDEN = ("origin", "source_id")  # jamais envoyés au navigateur


def want(n: int = N_CARDS) -> dict[str, int]:
    return {o: max(1, round(n * w)) for o, w in MIX.items()}


@lru_cache(maxsize=2)
def _pool(path: str, mtime: float) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["cards"]


def reference_pool(path: Path) -> list[dict]:
    """Lot fixe de cartes SSL / RLCS (vide s'il n'a pas encore été déposé)."""
    if not path.exists():
        return []
    return _pool(str(path), path.stat().st_mtime)


def create(conn: psycopg.Connection, player: str, pool: list[dict], seed: int | None = None) -> int:
    """Nouveau paquet en attente, avec ses cartes de référence ; retourne son identifiant."""
    from psycopg.types.json import Jsonb

    rng = random.Random(seed)
    w = want()
    ref = []
    for origin in ("ssl", "rlcs"):
        cards = [c for c in pool if c.get("origin") == origin]
        ref += rng.sample(cards, min(len(cards), w[origin]))
    row = conn.execute(
        "INSERT INTO swipe_decks (player_id, cards) VALUES (%s, %s) RETURNING id", (player, Jsonb(ref))
    ).fetchone()
    assert row is not None
    return int(row[0])


def pending(conn: psycopg.Connection, player: str, minutes: int = 15) -> int | None:
    """Paquet du joueur encore en préparation depuis moins de `minutes` (un seul à la fois)."""
    row = conn.execute(
        "SELECT id FROM swipe_decks WHERE player_id = %s AND status = 'en_attente' "
        "AND created_at > now() - make_interval(mins => %s) ORDER BY id DESC LIMIT 1",
        (player, minutes),
    ).fetchone()
    return int(row[0]) if row else None


def latest(conn: psycopg.Connection, player: str) -> dict | None:
    """Dernier paquet du joueur, cartes sans leur origine, avec ses jugements déjà faits."""
    row = conn.execute(
        "SELECT id, status, error, created_at, n_cards, cards FROM swipe_decks WHERE player_id = %s "
        "ORDER BY id DESC LIMIT 1",
        (player,),
    ).fetchone()
    if row is None:
        return None
    did, status, error, created, n, cards = row
    votes = dict(
        conn.execute(
            "SELECT card_id, verdict FROM swipe_judgments WHERE player_id = %s AND deck_id = %s", (player, did)
        ).fetchall()
    )
    ready = status == "pret"
    return {
        "id": did,
        "statut": status,
        "erreur": error,
        "cree_le": created,
        "n_cartes": n or 0,
        "cartes": [{k: v for k, v in c.items() if k not in HIDDEN} for c in cards] if ready and cards else [],
        "jugements": votes,
    }


def judge(conn: psycopg.Connection, player: str, deck_id: int, card_id: str, verdict: str) -> bool:
    """Enregistre (ou remplace) le jugement d'une carte d'un paquet prêt du joueur ; False si la carte est inconnue."""
    if verdict not in VERDICTS:
        raise ValueError(verdict)
    row = conn.execute(
        "SELECT c->>'origin', c->>'action' FROM swipe_decks d, jsonb_array_elements(d.cards) c "
        "WHERE d.id = %s AND d.player_id = %s AND d.status = 'pret' AND c->>'id' = %s",
        (deck_id, player, card_id),
    ).fetchone()
    if row is None:
        return False
    conn.execute(
        "INSERT INTO swipe_judgments (player_id, card_id, deck_id, verdict, origin, action) "
        "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (player_id, card_id) DO UPDATE SET deck_id = EXCLUDED.deck_id, "
        "verdict = EXCLUDED.verdict, origin = EXCLUDED.origin, action = EXCLUDED.action, judged_at = now()",
        (player, card_id, deck_id, verdict, row[0], row[1]),
    )
    return True


# ------------------------------------------------------------------------------------------------ worker


def teammates(conn: psycopg.Connection, player: str) -> list[str]:
    """Pseudos des 2 coéquipiers les plus fréquents (au moins MIN_GAMES_TOGETHER parties dans la même équipe)."""
    rows = conn.execute(
        "SELECT o.player_id, max(o.player_name), count(*) AS n FROM match_players me "
        "JOIN match_players o ON o.match_id = me.match_id AND o.team = me.team AND o.player_id <> me.player_id "
        "JOIN matches m ON m.id = me.match_id WHERE me.player_id = %s AND m.status IN ('ok', 'partiel') "
        "GROUP BY o.player_id HAVING count(*) >= %s ORDER BY n DESC, o.player_id LIMIT 2",
        (player, MIN_GAMES_TOGETHER),
    ).fetchall()
    return [name for _pid, name, _n in rows if name]


def finalize(cards: list[dict], deck_id: int) -> list[dict]:
    """Mélange et identifiants neutres : l'identifiant d'origine (« ssl:<replay>:<image> ») trahirait l'origine."""
    rng = random.Random(deck_id)
    cards = [dict(c) for c in cards]
    rng.shuffle(cards)
    for k, c in enumerate(cards, start=1):
        c["source_id"] = c["id"]
        c["id"] = f"{deck_id}-{k}"
    return cards


def build(
    conn: psycopg.Connection,
    cli: Any,
    bucket: str,
    deck_id: int,
    log: Callable[[str], None] = print,
) -> int:
    """Worker : complète le paquet avec les cartes des parties du joueur et le passe à « pret ». Retourne le nombre
    de cartes."""
    from psycopg.types.json import Jsonb

    from rlpi import swipe
    from rlpi.dashboard.storage import download_game

    row = conn.execute("SELECT player_id, cards, status FROM swipe_decks WHERE id = %s", (deck_id,)).fetchone()
    if row is None or row[2] != "en_attente":
        return 0
    player, ref_cards, _ = row
    tmp = Path(tempfile.mkdtemp(prefix="rlpi_swipe_"))
    try:
        # Seulement les parties dont le replay brut est dans le stockage (replay_key)
        rows = conn.execute(
            "SELECT m.id, m.replay_key FROM match_players mp JOIN matches m ON m.id = mp.match_id "
            "WHERE mp.player_id = %s AND m.status IN ('ok', 'partiel') AND m.replay_key IS NOT NULL "
            "ORDER BY random() LIMIT %s",
            (player, N_GAMES),
        ).fetchall()
        games = []
        for mid, key in rows:
            try:
                d = download_game(cli, bucket, mid, tmp / "games" / mid)
                raw = tmp / "raw" / f"{mid}.replay"
                raw.parent.mkdir(parents=True, exist_ok=True)
                cli.download_file(bucket, key, str(raw))
                games.append((d, raw))
            except Exception as e:  # noqa: BLE001 — partie incomplète dans le stockage : on en prend d'autres
                log(f"  swipe {deck_id} : partie {mid} ignorée ({type(e).__name__}: {e})"[:300])
        w = want()
        mine = swipe.player_cards(
            games,
            player,
            teammates(conn, player),
            {k: w[k] for k in ("perso", "peer", "lobby")},
            random.Random(deck_id),
        )
        cards = finalize([*ref_cards, *mine], deck_id)
        if not cards:
            raise RuntimeError("aucune carte : pas de partie exploitable")
        conn.execute(
            "UPDATE swipe_decks SET status = 'pret', cards = %s, n_cards = %s, ready_at = now(), error = NULL "
            "WHERE id = %s",
            (Jsonb(cards), len(cards), deck_id),
        )
        return len(cards)
    except Exception as e:
        conn.execute(
            "UPDATE swipe_decks SET status = 'erreur', error = %s WHERE id = %s",
            (f"{type(e).__name__}: {e}"[:500], deck_id),
        )
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
