"""Worker RLPI : traite les parties envoyées dans la file d'attente (version multi-joueurs, Coolify).

Circuit d'une partie :
    1. `enqueue` dépose le replay dans le stockage S3 (Garage), crée la ligne dans Postgres (statut en_attente)
       et ajoute une tâche dans la file Redis.
    2. Le worker prend la tâche, télécharge le replay, lance `rlpi.game run` (processus séparé), renvoie le dossier
       de la partie dans le stockage (users/<joueur>/games/<replay>/…) et met à jour Postgres (ok, partiel,
       rejetee ou erreur).
    3. Si le worker s'arrête en pleine partie (redémarrage, plantage), la tâche est remise dans la file au
       démarrage suivant. Une partie en erreur est retentée jusqu'à 3 fois.

Commandes (dans le conteneur du worker) :
    python -m rlpi.worker run                                  # boucle principale (commande par défaut de l'image)
    python -m rlpi.worker check                                # vérifie modèles, Redis, Postgres et stockage
    python -m rlpi.worker enqueue --user theo a.replay b.replay
    python -m rlpi.worker enqueue --user theo --ballchasing 3  # 3 parties 3v3 classées les plus récemment
                                                               # envoyées sur ballchasing (clé BALLCHASING_TOKEN)
    python -m rlpi.worker enqueue --user theo --ballchasing-id <id> <id>
    python -m rlpi.worker status [--user theo]                 # nombre de parties par statut, dernières erreurs

Variables d'environnement :
    REDIS_URL, DATABASE_URL                       URL internes données par Coolify
    S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY     Garage (clé rlpi-app) ; S3_BUCKET (rlpi), S3_REGION (garage)
    RLPI_MODELS                                   dossier des modèles (/app/models dans l'image)
    RLPI_KEEP_REPLAYS                             1 (défaut) garde le .replay dans le stockage, 0 le supprime
    RLPI_GAME_TIMEOUT                             durée maximale d'une partie en secondes (défaut 900)
    BALLCHASING_TOKEN                             facultatif, seulement pour enqueue --ballchasing
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

QUEUE = "rlpi:queue"
PROCESSING = "rlpi:processing:"  # + identifiant du worker
MAX_ATTEMPTS = 3
HEARTBEAT = Path(tempfile.gettempdir()) / "rlpi_worker_heartbeat"
REQUIRED_MODELS = ["value_h5.txt", "policy_touch.txt", "q_touch.txt", "placement_x.txt", "placement_y.txt",
                   "perf_reference.npz"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    user_id     text        NOT NULL,
    replay      text        NOT NULL,
    status      text        NOT NULL,   -- en_attente, en_cours, ok, partiel, rejetee, erreur
    replay_key  text,
    result      jsonb,
    error       text,
    wall_s      real,
    worker      text,
    attempts    integer     NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, replay)
);
CREATE INDEX IF NOT EXISTS games_status ON games (status);
"""


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def env(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    # Espaces et guillemets collés par erreur avec la valeur dans Coolify
    v = str(v).strip().strip("\"'").strip() if v is not None else ""
    if not v:
        raise SystemExit(f"Variable d'environnement manquante : {name}")
    return v


def url(name: str, schemes: tuple[str, ...]) -> str:
    """Lit une URL de connexion et vérifie son début, sans jamais afficher la valeur (elle contient un mot de passe)."""
    v = env(name)
    if not v.startswith(schemes):
        start = v.split("://")[0][:12] if "://" in v else "(pas de « :// »)"
        raise SystemExit(f"{name} doit commencer par {' ou '.join(schemes)} ; elle commence par : {start} "
                         f"({len(v)} caractères). Copier l'URL « internal » avec l'icône de copie dans Coolify.")
    return v


# --------------------------------------------------------------------------------------------------------------
# Connexions


def redis_client():
    import redis

    return redis.Redis.from_url(url("REDIS_URL", ("redis://", "rediss://")), decode_responses=True,
                                socket_timeout=60, socket_connect_timeout=10, health_check_interval=30)


def db():
    import psycopg

    return psycopg.connect(url("DATABASE_URL", ("postgres://", "postgresql://")), autocommit=True)


def s3():
    import boto3
    from botocore.config import Config

    endpoint = env("S3_ENDPOINT").rstrip("/")
    if not endpoint.startswith(("http://", "https://")) or " " in endpoint:
        # L'adresse ne contient pas de secret : on peut l'afficher pour aider à la corriger
        raise SystemExit(f"S3_ENDPOINT invalide : « {endpoint} ». Attendu : http://<nom du conteneur Garage>:3900, "
                         "par exemple http://garage-fj4rezthgm9pyk3rggqpjsw6:3900")
    return boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=env("S3_ACCESS_KEY"),
                        aws_secret_access_key=env("S3_SECRET_KEY"), region_name=env("S3_REGION", "garage"),
                        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 5}))


def bucket() -> str:
    return env("S3_BUCKET", "rlpi")


def models_dir() -> Path:
    from rlpi.config import MODELS

    return MODELS


def safe(s: str) -> str:
    """Identifiant utilisable dans une clé de stockage."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)[:120] or "_"


# --------------------------------------------------------------------------------------------------------------
# Envoi d'une partie dans la file


def enqueue(user: str, files: list[str]) -> None:
    r, cli, b = redis_client(), s3(), bucket()
    user = safe(user)
    with db() as conn:
        conn.execute(SCHEMA)
        for f in map(Path, files):
            if f.suffix.lower() != ".replay" or not f.is_file():
                log(f"ignoré (pas un fichier .replay) : {f}")
                continue
            key = f"users/{user}/replays/{safe(f.name)}"
            cli.upload_file(str(f), b, key)
            conn.execute(
                """INSERT INTO games (user_id, replay, status, replay_key) VALUES (%s, %s, 'en_attente', %s)
                   ON CONFLICT (user_id, replay) DO UPDATE
                   SET status = 'en_attente', replay_key = EXCLUDED.replay_key, error = NULL, attempts = 0,
                       updated_at = now()""",
                (user, f.stem, key))
            r.lpush(QUEUE, json.dumps({"user": user, "replay": f.stem, "key": key}))
            log(f"en file : {user}/{f.name}")


def enqueue_ballchasing(user: str, n: int = 0, ids: list[str] | None = None) -> None:
    """Télécharge des replays ballchasing puis les met en file. Utile pour tester sans copier de fichier sur le
    serveur. `ids` : identifiants de replays (publics, ou envoyés par le titulaire de la clé) ; `n` : les n parties
    3v3 classées les plus récemment envoyées par le titulaire de la clé API (BALLCHASING_TOKEN)."""
    from rlpi.config import ballchasing_api

    api = ballchasing_api()
    tmp = Path(tempfile.mkdtemp(prefix="rlpi_bc_"))
    try:
        todo = list(ids or [])
        if n:
            # « created » = date d'envoi sur ballchasing (l'API refuse « upload-date »)
            todo += [r["id"] for r in api.get_replays(uploader="me", playlist="ranked-standard", sort_by="created",
                                                      count=n)]
        files = []
        for rid in todo:
            files.append(str(api.download_replay(rid, tmp)))
            log(f"téléchargé depuis ballchasing : {rid}")
        if not files:
            log("aucune partie trouvée sur ballchasing")
        enqueue(user, files)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------------------------------------------
# Boucle du worker


class Worker:
    def __init__(self) -> None:
        self.id = safe(os.getenv("RLPI_WORKER_ID") or socket.gethostname())
        self.processing = PROCESSING + self.id
        self.stop = False
        self.keep_replays = os.getenv("RLPI_KEEP_REPLAYS", "1").strip() != "0"
        self.timeout = float(os.getenv("RLPI_GAME_TIMEOUT", "900"))
        self.r, self.s3, self.bucket = redis_client(), s3(), bucket()
        self.conn = db()
        self.conn.execute(SCHEMA)

    # Arrêt propre : Coolify envoie SIGTERM au redéploiement ; on finit la partie en cours.
    def _on_signal(self, *_):
        log("arrêt demandé : fin de la partie en cours puis sortie")
        self.stop = True

    def recover(self) -> None:
        """Remet dans la file les tâches restées « en cours » chez ce worker (arrêt brutal précédent)."""
        n = 0
        while self.r.lmove(self.processing, QUEUE, "RIGHT", "RIGHT"):  # reprises traitées en premier
            n += 1
        if n:
            log(f"{n} tâche(s) interrompue(s) remise(s) dans la file")

    def set_status(self, task: dict, status: str, **fields) -> None:
        from psycopg.types.json import Jsonb

        cols = ", ".join(f"{k} = %s" for k in fields)
        vals = [Jsonb(v) if k == "result" else v for k, v in fields.items()]
        self.conn.execute(
            f"UPDATE games SET status = %s{', ' + cols if cols else ''}, worker = %s, updated_at = now() "
            "WHERE user_id = %s AND replay = %s", [status, *vals, self.id, task["user"], task["replay"]])

    def upload_dir(self, local: Path, prefix: str) -> int:
        n = 0
        for f in local.rglob("*"):
            if f.is_file():
                self.s3.upload_file(str(f), self.bucket, f"{prefix}/{f.relative_to(local).as_posix()}")
                n += 1
        return n

    def process(self, raw: str) -> None:
        from rlpi import game

        task = json.loads(raw)
        user, replay, key = task["user"], task["replay"], task["key"]
        row = self.conn.execute("UPDATE games SET status = 'en_cours', attempts = attempts + 1, worker = %s, "
                                "updated_at = now() WHERE user_id = %s AND replay = %s RETURNING attempts",
                                (self.id, user, replay)).fetchone()
        attempts = row[0] if row else 1
        log(f"début {user}/{replay} (essai {attempts})")
        tmp = Path(tempfile.mkdtemp(prefix="rlpi_"))
        try:
            local = tmp / f"{replay}.replay"
            self.s3.download_file(self.bucket, key, str(local))
            out = tmp / "partie"
            res = game.run(local, out, models_dir(), timeout=self.timeout)
            prefix = f"users/{user}/games/{safe(replay)}"
            n = self.upload_dir(out, prefix)
            status = res["status"] if res["status"] in ("ok", "partiel", "rejetee") else "erreur"
            err = res.get("reason") or (json.dumps(res["errors"], ensure_ascii=False) if res.get("errors") else None)
            if status == "erreur":
                err = res.get("error", "erreur inconnue")[-2000:]
            summary = {k: v for k, v in res.items() if not k.startswith("traceback_")}
            self.set_status(task, status, result=summary, error=err, wall_s=res.get("wall_s"))
            if status in ("ok", "partiel", "rejetee") and not self.keep_replays:
                self.s3.delete_object(Bucket=self.bucket, Key=key)
            log(f"fin {user}/{replay} : {status} en {res.get('wall_s')} s, {n} fichiers envoyés"
                + (f" — {err[:200]}" if err else ""))
            if status == "erreur" and attempts < MAX_ATTEMPTS:
                self.r.lpush(QUEUE, raw)
                log(f"  remise en file ({attempts}/{MAX_ATTEMPTS})")
        except Exception as e:  # noqa: BLE001 — stockage ou base indisponible, replay introuvable…
            msg = f"{type(e).__name__}: {e}"[:2000]
            log(f"échec {user}/{replay} : {msg}")
            try:
                self.set_status(task, "erreur", error=msg)
            except Exception as e2:  # noqa: BLE001
                log(f"  impossible de noter l'erreur dans Postgres : {e2}")
            if attempts < MAX_ATTEMPTS:
                self.r.lpush(QUEUE, raw)
                log(f"  remise en file ({attempts}/{MAX_ATTEMPTS})")
                time.sleep(5)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)
        missing = [m for m in REQUIRED_MODELS if not (models_dir() / m).exists()]
        if missing:
            raise SystemExit(f"Modèles manquants dans {models_dir()} : {', '.join(missing)}")
        self.recover()
        log(f"worker {self.id} prêt (modèles : {models_dir()}, file : {QUEUE})")
        while not self.stop:
            HEARTBEAT.touch()
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
        missing = [m for m in REQUIRED_MODELS if not (models_dir() / m).exists()]
        if missing:
            raise FileNotFoundError(f"manquants dans {models_dir()} : {', '.join(missing)}")
        return f"{len(REQUIRED_MODELS)} fichiers présents dans {models_dir()}"

    def red():
        r = redis_client()
        r.ping()
        return f"connecté, {r.llen(QUEUE)} tâche(s) en file"

    def pg():
        with db() as c:
            c.execute(SCHEMA)
            return f"connecté, {c.execute('SELECT count(*) FROM games').fetchone()[0]} partie(s) en base"

    def store():
        cli, b = s3(), bucket()
        cli.put_object(Bucket=b, Key="_check/ping.txt", Body=b"ok")
        cli.delete_object(Bucket=b, Key="_check/ping.txt")
        return f"bucket {b} : écriture et suppression OK"

    import subtr_actor  # noqa: F401 — vérifie que le parseur est installé
    line("modèles", models)
    line("Redis", red)
    line("Postgres", pg)
    line("stockage", store)
    sys.exit(0 if ok else 1)


def status(user: str | None) -> None:
    with db() as c:
        c.execute(SCHEMA)
        where, args = ("WHERE user_id = %s", [safe(user)]) if user else ("", [])
        for st, n, avg in c.execute(f"SELECT status, count(*), avg(wall_s) FROM games {where} GROUP BY status "
                                    "ORDER BY status", args).fetchall():
            log(f"{st:<11} {n:>5} partie(s)" + (f", {avg:.1f} s en moyenne" if avg else ""))
        for u, rp, st, err in c.execute(f"SELECT user_id, replay, status, error FROM games {where} "
                                        f"{'AND' if where else 'WHERE'} error IS NOT NULL "
                                        "ORDER BY updated_at DESC LIMIT 5", args).fetchall():
            log(f"  {u}/{rp} [{st}] {err[:200]}")
    log(f"file Redis : {redis_client().llen(QUEUE)} tâche(s) en attente")


def main() -> None:
    ap = argparse.ArgumentParser(description="Worker RLPI")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("run")
    sub.add_parser("check")
    s = sub.add_parser("enqueue")
    s.add_argument("--user", required=True, help="identifiant du joueur (dossier dans le stockage)")
    s.add_argument("files", nargs="*")
    s.add_argument("--ballchasing", type=int, metavar="N", default=0,
                   help="mettre en file les N parties classées 3v3 les plus récemment envoyées sur ballchasing")
    s.add_argument("--ballchasing-id", nargs="+", default=[], metavar="ID", help="identifiants de replays ballchasing")
    s = sub.add_parser("status")
    s.add_argument("--user")
    a = ap.parse_args()
    if a.cmd in (None, "run"):
        Worker().run()
    elif a.cmd == "check":
        check()
    elif a.cmd == "enqueue":
        if a.ballchasing or a.ballchasing_id:
            enqueue_ballchasing(a.user, a.ballchasing, a.ballchasing_id)
        if a.files:
            enqueue(a.user, a.files)
        if not (a.files or a.ballchasing or a.ballchasing_id):
            ap.error("donner des fichiers .replay, --ballchasing N ou --ballchasing-id ID…")
    else:
        status(a.user)


if __name__ == "__main__":
    main()
