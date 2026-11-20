-- Version du calcul des agrégats au moment de l'abandon (tâches « aggregate » seulement, NULL sinon).
-- Le rattrapage périodique du worker saute les parties en lettre morte pour la version courante, mais les reprend
-- quand VERSION augmente : la nouvelle version du calcul corrige peut-être ce qui avait échoué.
ALTER TABLE dead_tasks ADD COLUMN version integer;
