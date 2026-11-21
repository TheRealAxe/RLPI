-- Ralentis en base (V9) abandonnés : les clips « ▶ Revoir » sont découpés par l'API à la demande, depuis le replay
-- gardé sur Garage (rlpi.web.clips), avec un cache en mémoire. La table ne contenait que des clips recalculables.
DROP TABLE IF EXISTS clips;
