-- matches.status limité aux valeurs connues. Si une ligne a un autre statut, la migration s'arrête (transaction
-- annulée) en listant les lignes fautives : rien n'est modifié.
DO $$
DECLARE
    fautives text;
BEGIN
    SELECT string_agg(format('%s (%s)', id, status), ', ' ORDER BY id) INTO fautives
    FROM matches
    WHERE status NOT IN ('en_attente', 'en_cours', 'ok', 'partiel', 'rejetee', 'erreur', 'doublon');
    IF fautives IS NOT NULL THEN
        RAISE EXCEPTION 'statut inconnu dans matches : %', fautives;
    END IF;
END $$;

ALTER TABLE matches ADD CONSTRAINT matches_status_check
    CHECK (status IN ('en_attente', 'en_cours', 'ok', 'partiel', 'rejetee', 'erreur', 'doublon'));
