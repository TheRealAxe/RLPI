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


def download_interval() -> float:
    """Secondes entre deux téléchargements ballchasing, tous workers confondus. Compte « regular » : 200 par heure,
    soit 18 s (limites de la librairie python-ballchasing ; gold 9 s, diamond 3,6 s, champion 1,8 s)."""
    return float(os.getenv("RLPI_BC_DOWNLOAD_INTERVAL", "18"))


def wait_download_slot(r) -> None:
    """Limite commune à tous les workers : un téléchargement ballchasing au plus toutes les download_interval() s."""
    ms = int(download_interval() * 1000)
    while not r.set("rlpi:bc_download", "1", nx=True, px=ms):
        time.sleep(max(r.pttl("rlpi:bc_download"), 100) / 1000)


def fetch_replay(match_id: str, conn, r, cli, api=None) -> str:
    """Télécharge le replay d'une partie ballchasing et le dépose dans le stockage. Retourne sa clé."""
    from rlpi.config import ballchasing_api

    api = api or ballchasing_api()
    key = f"replays/{match_id}.replay"
    tmp = Path(tempfile.mkdtemp(prefix="rlpi_dl_"))
    try:
        wait_download_slot(r)
        f = api.download_replay(match_id, tmp)
        cli.upload_file(str(f), store.bucket(), key)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    conn.execute("UPDATE matches SET replay_key = %s, updated_at = now() WHERE id = %s", (key, match_id))
    return key


def sync_player(player_id: str, log=print, conn=None, r=None, cli=None, api=None) -> int:
    """Met en file les nouvelles parties ballchasing d'un joueur inscrit. Retourne le nombre de parties ajoutées.

    Ne télécharge rien (la liste est rapide) : chaque partie est téléchargée par le worker qui la traite, pour que
    les premières parties soient traitées sans attendre la fin de tous les téléchargements.
    """
    from rlpi.config import ballchasing_api

    conn = conn or store.connect()
    r = r or store.redis_client()
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
    conn.execute("UPDATE accounts SET sync_started = now() WHERE player_id = %s", (player_id,))
    try:
        for rep in api.get_replays(**query):
            created = _ts(rep.get("created"))
            if created and (newest is None or created > newest):
                newest = created
            ins = conn.execute(
                "INSERT INTO matches (id, source, status, played_at) VALUES (%s, 'ballchasing', 'en_attente', %s) "
                "ON CONFLICT (id) DO NOTHING RETURNING id", (rep["id"], store.played_at(rep.get("date"))))
            if ins.fetchone():
                store.push_match(r, rep["id"])
                added += 1
    finally:
        conn.execute("UPDATE accounts SET last_sync = now(), synced_until = %s WHERE player_id = %s",
                     (newest, player_id))
    log(f"sync {player_id} : {added} nouvelle(s) partie(s) en file")
    return added


def sync_all(log=print, conn=None, r=None) -> int:
    """Passe sur tous les comptes. Un seul worker à la fois (verrou Redis)."""
    conn = conn or store.connect()
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
