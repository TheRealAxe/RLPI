-- Ralentis des touches les plus coûteuses (« Revoir » dans « À travailler », rlpi.clips).
-- Un clip par partie, joueur et touche (image à 10 i/s de touch_values), fabriqué à la demande par le worker à partir
-- du replay brut : positions, vitesses, orientation et boost des 6 voitures et de la balle, à 30 images/s.
CREATE TABLE clips (
    match_id    text        NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    player_id   text        NOT NULL,
    i           integer     NOT NULL,
    status      text        NOT NULL DEFAULT 'en_attente'
                CHECK (status IN ('en_attente', 'pret', 'erreur')),
    error       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    ready_at    timestamptz,
    clip        jsonb,
    PRIMARY KEY (match_id, player_id, i)
);
CREATE INDEX clips_pending ON clips (match_id, player_id) WHERE status = 'en_attente';
