"""Worker RLPI : traite les parties de la file d'attente et va chercher les nouvelles parties sur ballchasing.

Tâches de la file Redis (voir rlpi.store) :
    {"type": "match", "match": <id>}   télécharger replays/<id>.replay, lancer rlpi.game run (processus séparé),
                                       envoyer le résultat dans games/<id>/, noter le statut et les 6 joueurs
                                       dans Postgres (matches, match_players)
    {"type": "sync", "player": <id>}   chercher sur ballchasing les nouvelles parties de ce joueur (rlpi.collector)

En plus, toutes les RLPI_SYNC_MINUTES (défaut 15), un des workers passe sur tous les joueurs inscrits.
Une tâche interrompue (redémarrage) est remise en file au démarrage ; une partie en erreur est retentée 3 fois.
Un même match envoyé deux fois sur ballchasing (même GUID) n'est compté qu'une fois (statut « doublon »).

Commandes (dans le conteneur du worker, ou via `docker exec <conteneur> …`) :
    python -m rlpi.worker run                         # boucle principale (commande par défaut de l'image)
    python -m rlpi.worker check                       # vérifie modèles, Redis, Postgres, stockage, ballchasing
    python -m rlpi.worker add-player Steam:7656…      # inscrire un joueur sans passer par le site, puis sync
    python -m rlpi.worker sync [--player Steam:…]     # chercher maintenant les nouvelles parties
    python -m rlpi.worker enqueue a.replay …          # traiter des fichiers .replay
    python -m rlpi.worker enqueue --ballchasing-id <id> …
    python -m rlpi.worker status                      # parties par statut, dernières erreurs, joueurs inscrits

Variables d'environnement :
    REDIS_URL, DATABASE_URL                       URL internes données par Coolify
    S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY     Garage ; S3_BUCKET (rlpi), S3_REGION (garage)
    BALLCHASING_TOKEN                             clé API ballchasing du serveur (recherche des parties)
    RLPI_MODELS                                   dossier des modèles (/app/models dans l'image)
    RLPI_SYNC_MINUTES                             intervalle des recherches automatiques (défaut 15, 0 = jamais)
    RLPI_FIRST_SYNC                               parties importées au premier passage d'un joueur (défaut 50)
    RLPI_BC_DOWNLOAD_INTERVAL                     secondes entre deux téléchargements ballchasing, tous workers
                                                  confondus (défaut 18 : compte « regular », 200 par heure)
    RLPI_KEEP_REPLAYS                             1 (défaut) garde le .replay dans le stockage, 0 le supprime
    RLPI_GAME_TIMEOUT                             durée maximale d'une partie en secondes (défaut 900)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import sys
import tempfile
import time
from pathlib import Path

from rlpi import collector, store
from rlpi.store import PROCESSING, QUEUE, safe

MAX_ATTEMPTS = 3
HEARTBEAT = Path(tempfile.gettempdir()) / "rlpi_worker_heartbeat"
REQUIRED_MODELS = ["value_h5.txt", "policy_touch.txt", "q_touch.txt", "placement_x.txt", "placement_y.txt",
                   "perf_reference.npz"]


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def models_dir() -> Path:
    from rlpi.config import MODELS

    return MODELS


# --------------------------------------------------------------------------------------------------------------
# Mise en file manuelle


def enqueue_files(files: list[str]) -> None:
    r, cli, b, conn = store.redis_client(), store.s3(), store.bucket(), store.db()
    for f in map(Path, files):
        if f.suffix.lower() != ".replay" or not f.is_file():
            log(f"ignoré (pas un fichier .replay) : {f}")
            continue
        mid = safe(f.stem)
        key = f"replays/{mid}.replay"
        cli.upload_file(str(f), b, key)
        conn.execute("""INSERT INTO matches (id, source, status, replay_key) VALUES (%s, 'fichier', 'en_attente', %s)
                        ON CONFLICT (id) DO UPDATE SET status = 'en_attente', error = NULL, attempts = 0,
                        updated_at = now()""", (mid, key))
        store.push_match(r, mid)
        log(f"en file : {mid}")


def enqueue_ballchasing(ids: list[str]) -> None:
    from rlpi.config import ballchasing_api

    api, tmp = ballchasing_api(), Path(tempfile.mkdtemp(prefix="rlpi_bc_"))
    try:
        enqueue_files([str(api.download_replay(i, tmp)) for i in ids])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def add_player(player_id: str, name: str | None = None) -> None:
    conn, r = store.db(), store.redis_client()
    conn.execute("INSERT INTO accounts (player_id, name) VALUES (%s, %s) ON CONFLICT (player_id) DO NOTHING",
                 (player_id, name))
    store.push_sync(r, player_id)
    log(f"joueur inscrit : {player_id} ; recherche de ses parties en file")


# --------------------------------------------------------------------------------------------------------------
# Boucle du worker


class Worker:
    def __init__(self) -> None:
        self.id = safe(os.getenv("RLPI_WORKER_ID") or socket.gethostname())
        self.processing = PROCESSING + self.id
        self.stop = False
        self.keep_replays = os.getenv("RLPI_KEEP_REPLAYS", "1").strip() != "0"
        self.timeout = float(os.getenv("RLPI_GAME_TIMEOUT", "900"))
        self.sync_every = float(os.getenv("RLPI_SYNC_MINUTES", "15")) * 60
        self.last_sync = 0.0
        self.r, self.s3, self.bucket = store.redis_client(), store.s3(), store.bucket()
        self.conn = store.db()

    def bc_api(self):
        if getattr(self, "_bc", None) is None:
            from rlpi.config import ballchasing_api

            self._bc = ballchasing_api()
        return self._bc

    # Arrêt propre : Coolify envoie SIGTERM au redéploiement ; on finit la tâche en cours.
    def _on_signal(self, *_):
        log("arrêt demandé : fin de la tâche en cours puis sortie")
        self.stop = True

    def recover(self) -> None:
        """Remet dans la file les tâches restées « en cours » chez ce worker (arrêt brutal précédent)."""
        n = 0
        while self.r.lmove(self.processing, QUEUE, "RIGHT", "RIGHT"):  # reprises traitées en premier
            n += 1
        if n:
            log(f"{n} tâche(s) interrompue(s) remise(s) dans la file")

    def set_status(self, mid: str, status: str, **fields) -> None:
        from psycopg.types.json import Jsonb

        cols = "".join(f", {k} = %s" for k in fields)
        vals = [Jsonb(v) if k == "result" else v for k, v in fields.items()]
        self.conn.execute(f"UPDATE matches SET status = %s{cols}, worker = %s, updated_at = now() WHERE id = %s",
                          [status, *vals, self.id, mid])

    def upload_dir(self, local: Path, prefix: str) -> int:
        n = 0
        for f in local.rglob("*"):
            if f.is_file():
                self.s3.upload_file(str(f), self.bucket, f"{prefix}/{f.relative_to(local).as_posix()}")
                n += 1
        return n

    def requeue(self, raw: str, attempts: int) -> None:
        if attempts < MAX_ATTEMPTS:
            self.r.lpush(QUEUE, raw)
            log(f"  remise en file ({attempts}/{MAX_ATTEMPTS})")
            time.sleep(5)

    def process_match(self, raw: str, mid: str) -> None:
        from rlpi import game

        row = self.conn.execute("UPDATE matches SET status = 'en_cours', attempts = attempts + 1, worker = %s, "
                                "updated_at = now() WHERE id = %s RETURNING attempts, replay_key",
                                (self.id, mid)).fetchone()
        if row is None:
            log(f"partie inconnue dans Postgres, ignorée : {mid}")
            return
        attempts, key = row
        log(f"début {mid} (essai {attempts})")
        tmp = Path(tempfile.mkdtemp(prefix="rlpi_"))
        try:
            if not key:  # partie trouvée sur ballchasing : on la télécharge maintenant (limite commune de débit)
                key = collector.fetch_replay(mid, self.conn, self.r, self.s3, self.bc_api())
            local = tmp / f"{mid}.replay"
            self.s3.download_file(self.bucket, key, str(local))
            out = tmp / "partie"
            res = game.run(local, out, models_dir(), timeout=self.timeout)
            status = res["status"] if res["status"] in ("ok", "partiel", "rejetee") else "erreur"
            guid = res.get("match_guid")
            if status in ("ok", "partiel") and guid:
                dup = self.conn.execute("SELECT id FROM matches WHERE match_guid = %s AND id <> %s AND status IN "
                                        "('ok', 'partiel')", (guid, mid)).fetchone()
                if dup:
                    status = "doublon"
                    res["doublon_de"] = dup[0]
            n = self.upload_dir(out, f"games/{mid}") if status in ("ok", "partiel") else 0
            err = res.get("reason") or (json.dumps(res["errors"], ensure_ascii=False) if res.get("errors") else None)
            if status == "erreur":
                err = res.get("error", "erreur inconnue")[-2000:]
            summary = {k: v for k, v in res.items() if not k.startswith("traceback_")}
            self.set_status(mid, status, result=summary, error=err, wall_s=res.get("wall_s"), match_guid=guid,
                            played_at=res.get("date"))
            if status in ("ok", "partiel"):
                self.conn.execute("DELETE FROM match_players WHERE match_id = %s", (mid,))
                for p in res.get("players", []):
                    self.conn.execute("INSERT INTO match_players (match_id, player_id, player_name, team) "
                                      "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                                      (mid, p["id"], p.get("name"), p.get("team")))
            if status != "erreur" and not self.keep_replays:
                self.s3.delete_object(Bucket=self.bucket, Key=key)
            log(f"fin {mid} : {status} en {res.get('wall_s')} s, {n} fichiers envoyés"
                + (f" — {err[:200]}" if err else ""))
            if status == "erreur":
                self.requeue(raw, attempts)
        except Exception as e:  # noqa: BLE001 — stockage ou base indisponible, replay introuvable…
            msg = f"{type(e).__name__}: {e}"[:2000]
            log(f"échec {mid} : {msg}")
            try:
                self.set_status(mid, "erreur", error=msg)
            except Exception as e2:  # noqa: BLE001
                log(f"  impossible de noter l'erreur dans Postgres : {e2}")
            self.requeue(raw, attempts)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def process(self, raw: str) -> None:
        task = json.loads(raw)
        if task.get("type") == "sync":
            try:
                collector.sync_player(task["player"], log, self.conn, self.r, api=self.bc_api())
            except Exception as e:  # noqa: BLE001
                log(f"sync {task['player']} : échec {type(e).__name__}: {e}"[:500])
        elif task.get("type") == "match":
            self.process_match(raw, task["match"])
        else:
            log(f"tâche inconnue ignorée : {raw[:200]}")

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)
        missing = [m for m in REQUIRED_MODELS if not (models_dir() / m).exists()]
        if missing:
            raise SystemExit(f"Modèles manquants dans {models_dir()} : {', '.join(missing)}")
        self.recover()
        log(f"worker {self.id} prêt (modèles : {models_dir()}, recherche ballchasing toutes les "
            f"{self.sync_every / 60:.0f} min)")
        while not self.stop:
            HEARTBEAT.touch()
            if self.sync_every and time.time() - self.last_sync > self.sync_every and os.getenv("BALLCHASING_TOKEN"):
                self.last_sync = time.time()
                try:
                    collector.sync_all(log, self.conn, self.r)
                except Exception as e:  # noqa: BLE001
                    log(f"recherche automatique : échec {type(e).__name__}: {e}"[:500])
            raw = self.r.blmove(QUEUE, self.processing, timeout=20, src="RIGHT", dest="LEFT")
            if raw is None:
                continue
            self.process(raw)
            self.r.lrem(self.processing, 1, raw)
        log("worker arrêté")


# --------------------------------------------------------------------------------------------------------------
# Contrôles


def check() -> None:
    ok = True

    def line(name, fn):
        nonlocal ok
        try:
            log(f"OK      {name} : {fn()}")
        except BaseException as e:  # noqa: BLE001
            ok = False
            log(f"ÉCHEC   {name} : {type(e).__name__}: {e}")

    def models():
        import subtr_actor  # noqa: F401 — le parseur de replays est installé

        missing = [m for m in REQUIRED_MODELS if not (models_dir() / m).exists()]
        if missing:
            raise FileNotFoundError(f"manquants dans {models_dir()} : {', '.join(missing)}")
        return f"{len(REQUIRED_MODELS)} fichiers présents dans {models_dir()}"

    def red():
        r = store.redis_client()
        r.ping()
        return f"connecté, {r.llen(QUEUE)} tâche(s) en file"

    def pg():
        with store.db() as c:
            n = c.execute("SELECT count(*) FROM matches").fetchone()[0]
            a = c.execute("SELECT count(*) FROM accounts").fetchone()[0]
            return f"connecté, {n} partie(s), {a} joueur(s) inscrit(s)"

    def stockage():
        cli, b = store.s3(), store.bucket()
        cli.put_object(Bucket=b, Key="_check/ping.txt", Body=b"ok")
        cli.delete_object(Bucket=b, Key="_check/ping.txt")
        return f"bucket {b} : écriture et suppression OK"

    def ballchasing():
        from rlpi.config import ballchasing_api

        info = ballchasing_api().ping()
        return f"clé valide (compte {info.get('name')}, abonné : {'oui' if info.get('chaser') else 'non'})"

    line("modèles", models)
    line("Redis", red)
    line("Postgres", pg)
    line("stockage", stockage)
    line("ballchasing", ballchasing)
    sys.exit(0 if ok else 1)


def status() -> None:
    with store.db() as c:
        for st, n, avg in c.execute("SELECT status, count(*), avg(wall_s) FROM matches GROUP BY status "
                                    "ORDER BY status").fetchall():
            log(f"{st:<11} {n:>5} partie(s)" + (f", {avg:.1f} s en moyenne" if avg else ""))
        for mid, st, err in c.execute("SELECT id, status, error FROM matches WHERE error IS NOT NULL "
                                      "ORDER BY updated_at DESC LIMIT 5").fetchall():
            log(f"  {mid} [{st}] {err[:200]}")
        for pid, name, last, n in c.execute(
                "SELECT a.player_id, a.name, a.last_sync, (SELECT count(*) FROM match_players mp JOIN matches m "
                "ON m.id = mp.match_id WHERE mp.player_id = a.player_id AND m.status IN ('ok', 'partiel')) "
                "FROM accounts a ORDER BY a.created_at").fetchall():
            log(f"joueur {pid} ({name or '?'}) : {n} partie(s) traitée(s), dernière recherche {last or 'jamais'}")
    log(f"file Redis : {store.redis_client().llen(QUEUE)} tâche(s) en attente")


def main() -> None:
    ap = argparse.ArgumentParser(description="Worker RLPI")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("run")
    sub.add_parser("check")
    sub.add_parser("status")
    s = sub.add_parser("add-player")
    s.add_argument("player_id", help="identifiant comme dans les replays, ex. Steam:76561198078330309")
    s.add_argument("--name")
    s = sub.add_parser("sync")
    s.add_argument("--player", help="un seul joueur (sinon tous)")
    s = sub.add_parser("enqueue")
    s.add_argument("files", nargs="*")
    s.add_argument("--ballchasing-id", nargs="+", default=[], metavar="ID", help="identifiants de replays ballchasing")
    a = ap.parse_args()
    if a.cmd in (None, "run"):
        Worker().run()
    elif a.cmd == "check":
        check()
    elif a.cmd == "status":
        status()
    elif a.cmd == "add-player":
        add_player(a.player_id, a.name)
    elif a.cmd == "sync":
        n = collector.sync_player(a.player, log) if a.player else collector.sync_all(log)
        log(f"{n} partie(s) mise(s) en file")
    else:
        if not (a.files or a.ballchasing_id):
            ap.error("donner des fichiers .replay ou --ballchasing-id ID…")
        if a.ballchasing_id:
            enqueue_ballchasing(a.ballchasing_id)
        if a.files:
            enqueue_files(a.files)


if __name__ == "__main__":
    main()
