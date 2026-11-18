-- Sessions révocables (rlpi.web.sessions) et outil de jugement à l'aveugle « swipe » en ligne (rlpi.web.swipe).

-- Une ligne par session ouverte. Le cookie contient un jeton aléatoire ; seule son empreinte SHA-256 est gardée
-- ici (une copie de la table ne permet pas d'ouvrir une session). Se déconnecter supprime la ligne ; « se
-- déconnecter partout » supprime toutes celles du joueur.
CREATE TABLE sessions (
    id          text        PRIMARY KEY,            -- SHA-256 du jeton du cookie (hexadécimal)
    player_id   text        NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    last_used   timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL
);
CREATE INDEX sessions_player ON sessions (player_id);
CREATE INDEX sessions_expires ON sessions (expires_at);

-- Paquets de cartes à juger, un par demande. Fabriqués par le worker (cartes tirées des parties du joueur) et
-- complétés par des cartes SSL / RLCS d'un lot fixe ; l'origine de chaque carte reste en base, jamais envoyée au
-- navigateur (jugement à l'aveugle).
CREATE TABLE swipe_decks (
    id          bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_id   text        NOT NULL,
    status      text        NOT NULL DEFAULT 'en_attente'
                CHECK (status IN ('en_attente', 'pret', 'erreur')),
    error       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    ready_at    timestamptz,
    n_cards     integer,
    cards       jsonb                                 -- [{id, origin, action, fps, action_frame, ball, cars…}]
);
CREATE INDEX swipe_decks_player ON swipe_decks (player_id, id DESC);

-- Un jugement par joueur et par carte (le dernier compte). Origine et action recopiées depuis le paquet, pour
-- l'analyse sans relire les cartes.
CREATE TABLE swipe_judgments (
    player_id   text        NOT NULL,
    card_id     text        NOT NULL,
    deck_id     bigint      NOT NULL REFERENCES swipe_decks (id) ON DELETE CASCADE,
    verdict     text        NOT NULL CHECK (verdict IN ('bien', 'pas_bien', '?')),
    origin      text        NOT NULL,
    action      text,
    judged_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, card_id)
);
CREATE INDEX swipe_judgments_deck ON swipe_judgments (deck_id);
