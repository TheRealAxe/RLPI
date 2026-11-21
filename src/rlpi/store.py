"""Connexions et tables de la version multi-joueurs (Redis, Postgres, stockage S3 Garage).

Organisation :
- une partie (« match ») est traitée une seule fois, quel que soit le nombre de joueurs inscrits qui y figurent ;
  son identifiant est celui du replay sur ballchasing (ou le nom du fichier pour un envoi manuel) ;
- stockage : replays/<match>.replay et games/<match>/… (sortie de rlpi.game run) ;
- Postgres :
    accounts        joueurs inscrits (connexion Steam) : player_id « Steam:7656… »
    matches         une ligne par partie : statut du traitement, GUID du match (doublons), date…
    match_players   les 6 joueurs de chaque partie traitée → le tableau de bord d'un joueur = ses parties ici
- schéma Postgres : migrations Flyway de migrations/ (voir rlpi.migrate), vérifié par check_schema() ;
- Redis : file « rlpi:queue » de tâches JSON : {"type": "match", "match": id} ou {"type": "sync", "player": id}.
"""
from __future__ import annotations

import atexit
import json
import os
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from rlpi import logs

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    import psycopg
    import redis
    from psycopg_pool import ConnectionPool

QUEUE = "rlpi:queue"
PROCESSING = "rlpi:processing:"  # + identifiant du worker

# Le schéma de la base est défini par les migrations Flyway (migrations/V<n>__*.sql), jamais par ce code :
# le serveur et le worker vérifient seulement au démarrage que la base est au moins à cette version.
SCHEMA_VERSION = 10


class SchemaError(RuntimeError):
    """La base n'est pas à la version attendue (migrations Flyway non passées ou en échec)."""


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


def played_at(date: str | None) -> datetime | None:
    """Date d'une partie pour matches.played_at : « AAAA-MM-JJ HH-MM-SS » du replay (heure du replay, sans fuseau,
    enregistrée telle quelle en UTC) ou date ISO 8601 de ballchasing. None si absente ou illisible."""
    if not date:
        return None
    try:
        d = datetime.strptime(date, "%Y-%m-%d %H-%M-%S")
    except ValueError:
        try:
            d = datetime.fromisoformat(date.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def safe(s: str) -> str:
    """Identifiant utilisable dans une clé de stockage ou un nom de dossier."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)[:120] or "_"


def redis_client() -> redis.Redis:
    import redis

    return redis.Redis.from_url(url("REDIS_URL", ("redis://", "rediss://")), decode_responses=True,
                                socket_timeout=60, socket_connect_timeout=10, health_check_interval=30)


_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()
_schema_ok = False


def scalar(conn: psycopg.Connection, query: Any, params: Any = None) -> Any:
    """Première colonne de la première ligne d'une requête (qui doit renvoyer une ligne)."""
    row = conn.execute(query, params).fetchone()
    if row is None:
        raise LookupError("la requête n'a renvoyé aucune ligne")
    return row[0]


def schema_version(conn: psycopg.Connection) -> int | None:
    """Version du schéma d'après l'historique de Flyway (None si Flyway n'est jamais passé sur cette base)."""
    if scalar(conn, "SELECT to_regclass('flyway_schema_history')") is None:
        return None
    failed = conn.execute("SELECT version, description FROM flyway_schema_history WHERE NOT success "
                          "ORDER BY installed_rank").fetchall()
    if failed:
        raise SchemaError("migration Flyway en échec : " + ", ".join(f"V{v} {d}" for v, d in failed)
                          + " (voir « flyway info » et docs/REGLAGES_COOLIFY.md)")
    rows = conn.execute("SELECT version FROM flyway_schema_history WHERE success AND version IS NOT NULL").fetchall()
    return max((int(v.split(".")[0]) for (v,) in rows), default=None)


def check_schema(conn: psycopg.Connection) -> int:
    """Vérifie que la base est au moins à SCHEMA_VERSION ; aucune modification de la base. Retourne la version."""
    v = schema_version(conn)
    if v is None or v < SCHEMA_VERSION:
        found = "aucune migration Flyway" if v is None else f"version {v}"
        raise SchemaError(f"base de données à mettre à jour : {found}, version {SCHEMA_VERSION} attendue. "
                          "Lancer les migrations (python -m rlpi.migrate, ou le service flyway en local).")
    if v > SCHEMA_VERSION:
        logs.warning(f"Base en version {v}, plus récente que ce code ({SCHEMA_VERSION}) : on continue.")
    return v


def _check_once(conn: psycopg.Connection) -> None:
    global _schema_ok
    if not _schema_ok:
        check_schema(conn)
        _schema_ok = True


def pool() -> ConnectionPool:
    """Pool de connexions Postgres partagé par le processus, ouvert au premier appel (ou par init())."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                import psycopg
                from psycopg_pool import ConnectionPool

                p = ConnectionPool[psycopg.Connection](url("DATABASE_URL", ("postgres://", "postgresql://")), name="rlpi",
                                   min_size=1, max_size=int(os.getenv("RLPI_DB_POOL_MAX", "8")),
                                   kwargs={"autocommit": True}, timeout=30, open=True)
                try:
                    with p.connection() as c:
                        _check_once(c)
                except BaseException:
                    p.close()  # base injoignable ou pas à jour : on réessaiera au prochain appel
                    raise
                atexit.register(p.close)
                _pool = p
                return p
    return _pool


def init() -> None:
    """Au démarrage : ouvre le pool et vérifie la version du schéma (la première requête n'en paie pas le coût)."""
    pool()


def db() -> AbstractContextManager[psycopg.Connection]:
    """Connexion empruntée au pool, à utiliser avec « with store.db() as c: » (rendue au pool à la sortie)."""
    return pool().connection()


def connect() -> psycopg.Connection:
    """Connexion dédiée, gardée longtemps (boucle du worker, commandes en ligne). Version du schéma vérifiée une
    seule fois par processus."""
    import psycopg

    conn = psycopg.connect(url("DATABASE_URL", ("postgres://", "postgresql://")), autocommit=True)
    try:
        _check_once(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def s3() -> Any:  # client boto3 « s3 » (pas de types fournis par boto3)
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


def is_missing(e: Exception) -> bool:
    """Objet absent du stockage (boto3 : ClientError 404 / NoSuchKey ; FakeS3 des tests : FileNotFoundError)."""
    if isinstance(e, FileNotFoundError):
        return True
    code = str(getattr(e, "response", {}).get("Error", {}).get("Code", ""))
    return code in ("404", "NoSuchKey", "NotFound")


def push_match(r: redis.Redis, match_id: str) -> None:
    r.lpush(QUEUE, json.dumps({"type": "match", "match": match_id}))


def push_sync(r: redis.Redis, player_id: str) -> None:
    r.lpush(QUEUE, json.dumps({"type": "sync", "player": player_id}))
