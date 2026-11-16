-- matches.played_at : texte → timestamptz (filtres de période, index).
-- Valeurs existantes : date du replay « AAAA-MM-JJ HH-MM-SS » (heure du replay, sans fuseau : enregistrée telle
-- quelle en UTC), ou date ISO 8601 donnée par ballchasing pour une partie pas encore traitée. Une valeur illisible
-- est écrite dans le journal de la migration (RAISE NOTICE) puis mise à NULL.

CREATE FUNCTION pg_temp.lire_played_at(match_id text, v text) RETURNS timestamptz
LANGUAGE plpgsql AS $$
BEGIN
    IF v IS NULL OR btrim(v) = '' THEN
        RETURN NULL;
    END IF;
    IF v ~ '^\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}$' THEN
        RETURN to_timestamp(v, 'YYYY-MM-DD HH24-MI-SS')::timestamp AT TIME ZONE 'UTC';
    END IF;
    RETURN v::timestamptz;
EXCEPTION WHEN others THEN
    RAISE NOTICE 'played_at illisible, mis à NULL : partie %, valeur « % »', match_id, v;
    RETURN NULL;
END $$;

ALTER TABLE matches ALTER COLUMN played_at TYPE timestamptz USING pg_temp.lire_played_at(id, played_at);
CREATE INDEX matches_played_at ON matches (played_at);
