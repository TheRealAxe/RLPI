"""Récupération automatique des parties des joueurs inscrits sur ballchasing.com.

Pour chaque compte (identifiant Steam), on cherche sur ballchasing les parties 3v3 (classées et non classées) où
figure ce joueur, quel que soit celui qui les a envoyées, avec la clé API du serveur (BALLCHASING_TOKEN).
Chaque partie nouvelle est téléchargée, déposée dans le stockage (replays/<id>.replay), enregistrée dans Postgres
(matches, statut en_attente) et mise dans la file des workers.

- Premier passage d'un joueur : ses RLPI_FIRST_SYNC parties les plus récemment envoyées (défaut 50).
- Ensuite : seulement les parties envoyées sur ballchasing depuis le passage précédent.
- Une partie déjà connue (même identifiant ballchasing) n'est jamais retéléchargée ; un même match envoyé deux fois
  par deux joueurs est repéré après traitement grâce à son GUID (statut « doublon »).

Lancé par les workers : à l'inscription d'un joueur (tâche « sync ») et toutes les RLPI_SYNC_MINUTES (défaut 15).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path

from rlpi import store

PLAYLISTS = ["ranked-standard", "unranked-standard"]
SYNC_LOCK = "rlpi:sync_lock"


def first_sync() -> int:
    return int(os.getenv("RLPI_FIRST_SYNC", "50"))


def bc_player_id(player_id: str) -> str:
    """« Steam:7656… » (replays) → « steam:7656… » (filtre player-id de ballchasing)."""
    platform, _, pid = player_id.partition(":")
    return f"{platform.lower()}:{pid}"


def _ts(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def sync_player(player_id: str, log=print, conn=None, r=None, cli=None, api=None) -> int:
    """Met en file les nouvelles parties ballchasing d'un joueur inscrit. Retourne le nombre de parties ajoutées."""
    from rlpi.config import ballchasing_api

    conn = conn or store.db()
    r = r or store.redis_client()
    cli, b = cli or store.s3(), store.bucket()
    api = api or ballchasing_api()
    row = conn.execute("SELECT synced_until FROM accounts WHERE player_id = %s", (player_id,)).fetchone()
    if row is None:
        log(f"sync : compte inconnu {player_id}")
        return 0
    since = row[0]
    query = {"player_id": bc_player_id(player_id), "playlist": PLAYLISTS, "sort_by": "created", "sort_dir": "desc",
             "count": first_sync() if since is None else 1000}
    if since is not None:
        query["created_after"] = since.isoformat()
    newest, added = since, 0
    tmp = Path(tempfile.mkdtemp(prefix="rlpi_sync_"))
    try:
        for rep in api.get_replays(**query):
            created = _ts(rep.get("created"))
            if created and (newest is None or created > newest):
                newest = created
            rid = rep["id"]
            if conn.execute("SELECT 1 FROM matches WHERE id = %s", (rid,)).fetchone():
                continue
            f = api.download_replay(rid, tmp)
            key = f"replays/{rid}.replay"
            cli.upload_file(str(f), b, key)
            Path(f).unlink(missing_ok=True)
            ins = conn.execute(
                "INSERT INTO matches (id, source, status, replay_key, played_at) VALUES (%s, 'ballchasing', "
                "'en_attente', %s, %s) ON CONFLICT (id) DO NOTHING RETURNING id", (rid, key, rep.get("date")))
            if ins.fetchone():
                store.push_match(r, rid)
                added += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        conn.execute("UPDATE accounts SET last_sync = now(), synced_until = %s WHERE player_id = %s",
                     (newest, player_id))
    log(f"sync {player_id} : {added} nouvelle(s) partie(s) en file")
    return added


def sync_all(log=print, conn=None, r=None) -> int:
    """Passe sur tous les comptes. Un seul worker à la fois (verrou Redis)."""
    conn = conn or store.db()
    r = r or store.redis_client()
    if not r.set(SYNC_LOCK, str(time.time()), nx=True, ex=3600):
        return 0
    try:
        total = 0
        for (pid,) in conn.execute("SELECT player_id FROM accounts ORDER BY last_sync NULLS FIRST").fetchall():
            try:
                total += sync_player(pid, log, conn, r)
            except Exception as e:  # noqa: BLE001 — ballchasing indisponible pour ce joueur : on passe au suivant
                log(f"sync {pid} : échec {type(e).__name__}: {e}"[:500])
        return total
    finally:
        r.delete(SYNC_LOCK)
