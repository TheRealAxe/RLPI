"""Connexions et tables de la version multi-joueurs (Redis, Postgres, stockage S3 Garage).

Organisation :
- une partie (« match ») est traitée une seule fois, quel que soit le nombre de joueurs inscrits qui y figurent ;
  son identifiant est celui du replay sur ballchasing (ou le nom du fichier pour un envoi manuel) ;
- stockage : replays/<match>.replay et games/<match>/… (sortie de rlpi.game run) ;
- Postgres :
    accounts        joueurs inscrits (connexion Steam) : player_id « Steam:7656… »
    matches         une ligne par partie : statut du traitement, GUID du match (doublons), date…
    match_players   les 6 joueurs de chaque partie traitée → le tableau de bord d'un joueur = ses parties ici
- Redis : file « rlpi:queue » de tâches JSON : {"type": "match", "match": id} ou {"type": "sync", "player": id}.
"""
from __future__ import annotations

import json
import os

QUEUE = "rlpi:queue"
PROCESSING = "rlpi:processing:"  # + identifiant du worker

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    player_id    text        PRIMARY KEY,           -- « Steam:7656… », comme dans les replays
    name         text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_login   timestamptz,
    last_sync    timestamptz,                       -- dernière recherche sur ballchasing
    synced_until timestamptz                        -- date d'envoi sur ballchasing de la plus récente partie vue
);
CREATE TABLE IF NOT EXISTS matches (
    id            text        PRIMARY KEY,          -- identifiant ballchasing (ou nom du fichier)
    source        text        NOT NULL,             -- ballchasing | fichier
    status        text        NOT NULL,             -- en_attente, en_cours, ok, partiel, rejetee, erreur, doublon
    replay_key    text,
    match_guid    text,
    played_at     text,
    result        jsonb,
    error         text,
    wall_s        real,
    worker        text,
    attempts      integer     NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS matches_status ON matches (status);
CREATE INDEX IF NOT EXISTS matches_guid ON matches (match_guid);
CREATE TABLE IF NOT EXISTS match_players (
    match_id    text NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    player_id   text NOT NULL,
    player_name text,
    team        smallint,
    PRIMARY KEY (match_id, player_id)
);
CREATE INDEX IF NOT EXISTS match_players_player ON match_players (player_id);
"""


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


def safe(s: str) -> str:
    """Identifiant utilisable dans une clé de stockage ou un nom de dossier."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)[:120] or "_"


def redis_client():
    import redis

    return redis.Redis.from_url(url("REDIS_URL", ("redis://", "rediss://")), decode_responses=True,
                                socket_timeout=60, socket_connect_timeout=10, health_check_interval=30)


def db():
    import psycopg

    conn = psycopg.connect(url("DATABASE_URL", ("postgres://", "postgresql://")), autocommit=True)
    conn.execute(SCHEMA)
    return conn


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


def push_match(r, match_id: str) -> None:
    r.lpush(QUEUE, json.dumps({"type": "match", "match": match_id}))


def push_sync(r, player_id: str) -> None:
    r.lpush(QUEUE, json.dumps({"type": "sync", "player": player_id}))
