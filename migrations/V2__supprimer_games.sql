-- Table « games » d'une ancienne version du worker (commit d47dcb7) : aucun code ne l'utilise.
-- Contenu relevé en production le 2026-11-17 : 3 lignes d'essai du 2026-11-15, rien à conserver.
-- IF EXISTS : une base locale créée avant Flyway par l'ancien code ne l'a pas.
DROP TABLE IF EXISTS games;
