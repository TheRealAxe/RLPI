-- Tâches en échec définitif (« lettre morte », phase I de docs/PLAN_REFONTE_WEB.md).
-- Une ligne par tâche abandonnée par le worker : partie en erreur après ses 3 essais, agrégats impossibles à
-- calculer, tâche illisible. La tâche est gardée telle qu'elle était dans la file Redis (`task`), avec la cause et
-- le nombre d'essais ; `python -m rlpi.worker retry` la remet en file et note `retried_at`.
CREATE TABLE dead_tasks (
    id          bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind        text        NOT NULL,                 -- match, aggregate, swipe, inconnue…
    ref         text,                                 -- identifiant de la partie (ou du paquet) concerné
    task        jsonb       NOT NULL,                 -- tâche telle que lue dans la file
    error       text        NOT NULL,
    attempts    integer     NOT NULL DEFAULT 1,
    worker      text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    retried_at  timestamptz                           -- remise en file à la main ; NULL tant qu'elle attend
);
CREATE INDEX dead_tasks_pending ON dead_tasks (created_at DESC) WHERE retried_at IS NULL;
CREATE INDEX dead_tasks_ref ON dead_tasks (ref);
