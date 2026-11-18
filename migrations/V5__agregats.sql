-- Agrégats du tableau de bord (rlpi.dashboard.aggregate, rlpi.dashboard.storage), écrits par le worker après
-- chaque partie : le serveur ne lit plus que ces tables (et la référence) pour calculer le contenu d'une page.

-- Une ligne par partie : ce qui ne dépend que de la partie (date, score, joueurs, courbe de valeur, synergie)
CREATE TABLE game_aggregates (
    match_id    text        PRIMARY KEY REFERENCES matches (id) ON DELETE CASCADE,
    version     integer     NOT NULL,               -- version du calcul (rlpi.dashboard.aggregate.VERSION)
    replay      text        NOT NULL,               -- nom du replay dans les fichiers de la partie
    computed_at timestamptz NOT NULL DEFAULT now(),
    data        jsonb       NOT NULL
);

-- Une ligne par joueur et par partie : identité, indicateurs de la partie (colonnes typées : NaN possibles),
-- petits détails lus pour tous les joueurs (data) et détails lus seulement pour le joueur affiché (details)
CREATE TABLE player_game_aggregates (
    match_id    text        NOT NULL REFERENCES game_aggregates (match_id) ON DELETE CASCADE,
    player_id   text        NOT NULL,
    player_name text,
    team        smallint,
    in_stats    boolean     NOT NULL,               -- présent dans les stats (partie en ligne 3v3)
    is_bot      boolean,
    played      text,                               -- date du replay « AAAA-MM-JJ HH-MM-SS », comme dans le contenu
    won         smallint,                           -- 1 victoire, 0 défaite (comme dans les stats)
    team_goals  smallint,
    opp_goals   smallint,
    boost_moyen      double precision,
    boost_zero       double precision,
    boost_utilise    double precision,
    boost_petits     double precision,
    boost_vole       double precision,
    boost_gaspille   double precision,
    vitesse          double precision,
    supersonique     double precision,
    lent             double precision,
    au_sol           double precision,
    air_haut         double precision,
    ff_gagnes        double precision,
    ko_gagnes        double precision,
    ff_par5          double precision,
    tirs             double precision,
    buts             double precision,
    frappes_fortes   double precision,
    ratees           double precision,
    passes           double precision,
    demos            double precision,
    bumps            double precision,
    moitie_adverse   double precision,
    devant_balle     double precision,
    premier_homme    double precision,
    troisieme_homme  double precision,
    derriere_balle   double precision,
    t_speed          double precision,
    t_sup            double precision,
    t_slow           double precision,
    t_highair        double precision,
    t_haer           double precision,
    t_aer            double precision,
    t_wall           double precision,
    t_awhiff         double precision,
    t_beaten         double precision,
    data        jsonb       NOT NULL,
    details     jsonb       NOT NULL,
    PRIMARY KEY (match_id, player_id)
);
CREATE INDEX player_game_aggregates_player ON player_game_aggregates (player_id);

-- Partie fixe (références RLCS / SSL, rapports des modèles), recalculée quand ses fichiers changent
CREATE TABLE reference_aggregates (
    name        text        PRIMARY KEY,
    fingerprint text        NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT now(),
    data        jsonb       NOT NULL
);

-- Version des données de chaque joueur : augmentée à chaque partie (re)calculée où il figure (cache, ETag)
CREATE TABLE player_versions (
    player_id   text        PRIMARY KEY,
    version     bigint      NOT NULL DEFAULT 0,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
