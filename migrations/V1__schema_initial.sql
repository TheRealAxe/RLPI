-- Schéma initial : exactement la base de production au 2026-11-17 (pg_dump --schema-only, Postgres 18.7),
-- c'est-à-dire SCHEMA de rlpi/store.py avant Flyway, plus la table « games » d'une ancienne version.
-- En production, cette migration n'est PAS exécutée : la base existante est marquée à la version 1
-- (baselineOnMigrate, baselineVersion = 1). Elle crée le schéma d'une base vide (local, CI).

-- Joueurs inscrits (connexion Steam)
CREATE TABLE accounts (
    player_id    text        PRIMARY KEY,           -- « Steam:7656… », comme dans les replays
    name         text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_login   timestamptz,
    last_sync    timestamptz,                       -- dernière recherche sur ballchasing
    synced_until timestamptz                        -- date d'envoi sur ballchasing de la plus récente partie vue
);
ALTER TABLE accounts ADD COLUMN sync_started timestamptz;   -- début de la dernière recherche

-- Une ligne par partie : statut du traitement, GUID du match (doublons), date…
CREATE TABLE matches (
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
CREATE INDEX matches_status ON matches (status);
CREATE INDEX matches_guid ON matches (match_guid);

-- Les 6 joueurs de chaque partie traitée
CREATE TABLE match_players (
    match_id    text NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    player_id   text NOT NULL,
    player_name text,
    team        smallint,
    PRIMARY KEY (match_id, player_id)
);
CREATE INDEX match_players_player ON match_players (player_id);

-- Reste d'une ancienne version du worker (commit d47dcb7), plus utilisé : supprimé par V2
CREATE TABLE games (
    user_id     text        NOT NULL,
    replay      text        NOT NULL,
    status      text        NOT NULL,
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
CREATE INDEX games_status ON games (status);
