# Journal de la refonte web

Suivi de `docs/PLAN_REFONTE_WEB.md` : date, ce qui est fait, décisions, versions retenues, problèmes.
Le journal des modèles et des indicateurs reste dans `docs/JOURNAL.md`.

## 2026-11-17 — Phase A : corrections immédiates

Branche `feature/amelioration-logicielle`, un commit par étape.

### Fait

- **Environnement local** `docker-compose.dev.yml` : Postgres 18, Redis 8, Garage v2.3.0, serveur et worker (images
  de production construites en local). Configuration Garage de développement dans `dev/garage.toml` (secrets fixes,
  locaux seulement). `rlpi-data-lainox/` est monté en lecture seule sur `/app/data` du serveur, comme le volume de
  production (références RLCS/SSL, rapports des modèles, pages statiques). `data/raw/` est monté sur `/replays` du
  worker. Pas de recherche automatique sur ballchasing en local (`RLPI_SYNC_MINUTES=0`), 5 parties au premier
  passage (`RLPI_FIRST_SYNC=5`) ; le vrai `BALLCHASING_TOKEN` du `.env` est transmis.
- **Remplissage** `scripts/dev_setup.py` : configure Garage (rôle, bucket, clé importée), puis découpe les Parquet
  fusionnés de `rlpi-data-lainox/` partie par partie et écrit dans Garage (`games/<partie>/…`) et Postgres
  (`matches`, `match_players`) ce que le worker aurait produit. Aucun appel à ballchasing ; relançable sans doublon.
  Résultat : 45 parties (les fichiers en contiennent 45, et non environ 65), 0 doublon de GUID (20 parties sans GUID).
  Pas de tables `defense`, `kickoffs` ni `bestplay_*` dans `rlpi-data-lainox/` : le tableau de bord s'affiche quand
  même, sans ces parties.
- **Postgres** : pool `psycopg_pool` pour le serveur (`store.db()` emprunte une connexion, `store.init()` l'ouvre au
  démarrage) ; connexion dédiée `store.connect()` pour la boucle du worker et les commandes. Le schéma n'est
  exécuté qu'une fois par processus. `psycopg-pool` ajouté à `pyproject.toml` et aux deux Dockerfiles.
- **XSS** : le JSON inséré dans le gabarit échappe `<`, `>` et `&` (`serve.script_json`). Relecture des 47
  `innerHTML` du gabarit : les pseudos passaient déjà par `esc()` ; les identifiants de joueur et de partie
  insérés dans des attributs (`value`, `data-replay`) y passent maintenant aussi.
- **Journal d'accès** : une ligne par requête (date, méthode, chemin sans paramètres, statut, durée), jamais de
  cookie ; les sondes `/health` réussies ne sont pas écrites.
- **Compression** : le cache des pages garde les pages compressées (gzip, en mémoire comme sur disque) et les
  envoie telles quelles (`Content-Encoding: gzip`) ; décompression seulement pour un navigateur qui n'accepte pas
  gzip. Pour cela, le bandeau du bas (nombre de parties, message) fait partie de la page en cache (clé : nombre de
  parties et message).
- **En-têtes** : `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY` sur
  toutes les réponses ; l'en-tête `Server` n'affiche plus la version de Python.
- **POST /moi/actualiser** : l'en-tête `Origin` (à défaut `Referer`) doit correspondre à `RLPI_PUBLIC_URL`, sinon 403.
- **Connexion de développement** `/dev/connexion` (`RLPI_DEV_LOGIN=1`) : liste des joueurs des parties traitées,
  session ouverte sans Steam, compte créé sans lancer de recherche ballchasing. Le serveur refuse de démarrer si la
  variable est active et `RLPI_PUBLIC_URL` en `https://` ; la route répond 404 si elle est inactive.
- **Plus de tableau de bord public** : `/tableau_de_bord.html` et `/tableau_de_bord` renvoient vers `/moi` (en
  gardant `du`, `au`, `avec`, `sans`, sans `j`). Pré-calcul (`warm_defaults`, `warm_loop`), copie des données
  du joueur principal et option `--since` retirés.
- **Plus aucun joueur en dur** : `config.PLAYER` et `config.COMPARE` supprimés (et `RLPI_PLAYER`, `RLPI_COMPARE`,
  `RLPI_DEMOS`, `RLPI_SINCE` de `.env.example`) ; `styles.ME` supprimé (inutilisé) ; `swipe` reçoit `--player` et
  `--peers` ; `--player` obligatoire pour `dashboard`, `ghost`, `bestplay export|worst` ; exemples avec un
  identifiant fictif.
- **Mode local supprimé** : `app.py` et `dashboard_template_v1.html` supprimés ; le README (ancien « kit de
  lancement ») décrit maintenant l'environnement local. Aucun script d'installation du kit n'était versionné.
- `docs/REGLAGES_COOLIFY.md` créé (variables à retirer ou vérifier dans Coolify).

### Vérifications (en local, `docker-compose.dev.yml`)

- Théo (41 parties en local) : `/moi` calculé en 16,5 s la première fois, puis 3 ms depuis le cache ; 736 Ko
  envoyés en gzip au lieu de 2,07 Mo. Contenu complet (toutes les sections, 40 parties dans l'indice).
- Pseudo de test `</script><b>x` donné à un adversaire (dans Garage et Postgres) : présent tel quel dans les données
  de la page, un seul bloc `<script>`, rien de cassé ; échappé aussi dans `/dev/connexion`.
- 10 pages servies depuis le cache : 0 nouvelle connexion Postgres (journal `log_connections`, hors sondes
  `pg_isready`).
- Sans cookie : `/tableau_de_bord.html?j=x&du=…` → 303 vers `/moi?du=…`, qui affiche la page de connexion.
- POST `/moi/actualiser` : sans origine 403, origine étrangère 403, bonne origine 303. La recherche lancée par le
  bouton a trouvé 5 parties de Théo sur ballchasing, téléchargées et traitées par le worker local.
- Worker de bout en bout : les 5 replays de `data/raw/` mis en file (`rlpi.worker enqueue`) sont traités `ok`
  (12 à 17 s chacun, Redis → `rlpi.game run` → Garage → Postgres) ; base locale : 55 parties `ok`, file vide.
- Rileq (13 parties) : sa page est centrée sur lui ; `?j=` vers un joueur qui n'est pas un de ses coéquipiers
  proposés est ignoré. Test « chacun ne voit que le sien » concluant dans la mesure du possible en local.
- `grep` de l'identifiant Steam de Théo, `LAinox`, `Rileq`, `RLPI_PLAYER`, `RLPI_COMPARE` dans `src/` : aucun
  résultat.
- `ruff check --select F` : pas de nouvelle erreur (9 erreurs anciennes, hors du périmètre).

### Versions retenues

Postgres `postgres:18` (production 18.7), Redis `redis:8`, Garage `dxflrs/garage:v2.3.0`, Python 3.13.
Poste : psycopg 3.3.9, psycopg-pool 3.3.3, redis-py 8.1.0, boto3 1.44.4, polars 2.1.0, uv 0.13.8, Docker 29.6.2.

### Points ouverts

- Les pages statiques de `reports/` (`fantome.html`, `meilleur_jeu.html`, `swipe/`, données `*.js`) restent
  publiques et contiennent des données de Théo. Le plan ne les traite qu'en phases B (recensement) et F (portage) ;
  à décider si elles doivent être fermées plus tôt.
- Le gabarit affiche encore, en cas d'absence de données, un message du mode local (« reports/tableau_de_bord.html,
  pour la régénérer… ») ; il part avec le gabarit en phase H.
- Le premier calcul d'un tableau de bord reste lent (11 à 17 s en local) : traité en phases C et D.

## 2026-11-17 — Phase B : socle qualité

Branche `feature/amelioration-logicielle`, un commit par étape.

### Fait

- **Dépendances** : `uv` et `uv.lock` (seule source des versions). Socle commun (polars, numpy, pyarrow, psycopg,
  psycopg-pool, redis, boto3, python-dotenv) ; extra `server` (vide jusqu'à FastAPI en phase E) ; extra `worker`
  (LightGBM 4.7.0, scikit-learn, subtr-actor-py 1.5.1, python-ballchasing, requests). Les outils de développement
  sont dans le **groupe** `dev` (pytest, ruff, pyright, fakeredis) plutôt qu'un extra : `uv sync` les installe en
  local, `--no-dev` les exclut des images. Streamlit et pyyaml (inutilisés) retirés. Les Dockerfiles font
  `uv sync --frozen --no-dev --extra server|worker`. Python fixé à 3.13 (`>=3.13,<3.14`), comme les images.
- **Migrations Flyway** (DB first) : `migrations/V1__schema_initial.sql` (schéma de production relevé, table
  `games` comprise) et `V2__supprimer_games.sql`. Le serveur et le worker n'exécutent plus aucun `CREATE`/`ALTER` :
  `store.check_schema()` lit `flyway_schema_history` et refuse une base en dessous de `SCHEMA_VERSION` (2) ou avec
  une migration en échec ; une base plus récente est acceptée avec un message (retour arrière du code possible).
- **Flyway en production — décidé le 2026-11-17 avec Luc : dans l'image du serveur.** Coolify exécute la
  « pre-deployment command » dans l'**ancien** conteneur (sans les nouvelles migrations) : elle ne convient pas.
  L'image du serveur contient Flyway 13.12.0 réduit à Postgres, et Java (~240 Mo de plus) ; le conteneur lance
  `python -m rlpi.migrate` (variables `FLYWAY_*` calculées depuis `DATABASE_URL`, `baselineOnMigrate`,
  `baselineVersion=1`, `cleanDisabled`) puis le serveur. Si les migrations échouent, le conteneur ne démarre pas et
  Coolify garde l'ancienne version. Les workers attendent jusqu'à 5 min (`RLPI_SCHEMA_WAIT`) la bonne version.
  Écarté : une image de migration séparée lancée par la GitHub Action (ressource Coolify de plus, enchaînement
  fragile).
- **Local** : service `flyway` (image `flyway/flyway:13.12.0`) dans `docker-compose.dev.yml`, avant le serveur et
  le worker. Base locale existante : marquée version 1, puis V2 passée. Base vide : V1 + V2.
- **Jeu d'essai** `tests/fixtures/` (10 Mo, fabriqué par `scripts/make_fixtures.py`) : 8 parties du joueur suivi
  (6 avec ses deux coéquipiers, 2 sans eux) au format exact écrit par le worker dans Garage, 8 parties RLCS (deux
  affiches ; images réduites aux colonnes lues), 40 parties SSL, rapports des modèles (JSON). Identifiants, pseudos,
  noms de replays, GUID et chemins remplacés par des valeurs fictives cohérentes, y compris les joueurs d'exemple
  de `styles.json` ; le script relit tout ce qu'il produit et échoue s'il reste une valeur réelle.
  `make_payload()` n'a besoin d'aucun modèle LightGBM `.txt` (vérifié : seulement `styles.json`,
  `perf_report.json`, `value_h5_report.json`).
- **Tests** (pytest, 58) :
  - **instantané du tableau de bord** (`tests/snapshots/tableau_de_bord.json`) par le même chemin que `/moi`
    (`game.merge` → synergie → `players _inner payload`), pour 5 combinaisons de filtres (défaut, coéquipier,
    période, avec, sans). Seule la date de calcul est retirée ; nombres arrondis à 10 chiffres significatifs.
    Identique sous Windows et sous Linux.
  - session (cookie valide, expiré, falsifié, autre secret), connexion Steam (réponse simulée ; réponses invalides
    rejetées sans appel à Steam), routes du serveur (vrai serveur HTTP), worker (vraie boucle, Redis simulé par
    fakeredis, stockage simulé : traitement, erreurs et 3 essais, replay introuvable, doublon, reprise après arrêt
    brutal), migrations (version, base sans Flyway, migration en échec, attente du worker).
  - Les tests Postgres créent une base temporaire migrée (`RLPI_TEST_DATABASE_URL`) ; sans elle ils sont sautés
    (`uv sync && pytest` sur une machine Linux neuve : 41 réussis, 17 sautés). En CI, `RLPI_TEST_REQUIRE_DB=1`.
- **Ordre rendu déterministe** (révélé par l'instantané ; les chiffres ne changent pas) : liste des joueurs de
  référence (`compare`, `group_by` sans ordre), coéquipiers à égalité de parties (`players._profile_ids`), tirage
  de l'intervalle de la synergie (ordre des parties avant le tirage). En production, ces éléments pouvaient changer
  d'un calcul à l'autre.
- **ruff** sur tout le code (règles `E4 E7 E9 F W I B UP` ; style dense des modules d'analyse toléré : `E702`,
  `B023`, `B905`) ; 76 remarques corrigées (imports, variables inutilisées…), instantané inchangé. Mise en forme
  (`ruff format`) vérifiée seulement sur le code neuf ou repris (`tests/`, `scripts/`, `migrate.py`), élargie au
  fil des phases. **pyright** (mode standard) sans erreur sur `store`, `account`, `worker` et `migrate` :
  annotations complétées, `store.scalar()` pour les requêtes à une valeur, colonnes de `set_status` composées avec
  `psycopg.sql` (plus de SQL construit par f-string).
- **CI** : workflow `Tests` (push sur les branches, pull requests, appelé par `deploy.yml`) : contrôle des noms
  interdits (secret `RLPI_NOMS_INTERDITS`), `uv sync --frozen`, ruff, pyright, vrai Flyway sur une base vide
  (`migrate`, `validate`, `info`), puis pytest, dont une comparaison du schéma créé par le vrai Flyway avec celui
  des tests. `deploy.yml` : images et déploiement seulement si les tests passent.
- **Pages de `reports/`** : les pages écrites à la main (accueil, fantôme, meilleur jeu, swipe, deux prototypes)
  versionnées dans `web/legacy/` avec leur recensement (`web/legacy/README.md`) ; aucune donnée de joueur dedans.
  Fermeture des pages publiques qui montrent des données (fantôme, meilleur jeu) : **laissée en phase F** (décidé
  le 2026-11-17 avec Luc).

### Vérifications

- `docker-compose.dev.yml` reconstruit : Flyway passe V2 sur la base existante, le serveur relance les migrations
  (« up to date ») puis démarre ; un replay de `data/raw/` traité `ok` par le worker (16 s) ; `/moi` servi après
  connexion de développement (15,6 s au premier calcul, comme avant).
- Base vide migrée par Flyway (V1 + V2) et base locale créée par l'ancien code : `pg_dump --schema-only`
  identiques.
- Suite complète dans un conteneur Linux (`python:3.13-slim` + uv) : 57 réussis, 1 sauté (vrai Flyway, CI
  seulement), instantané identique à celui fait sous Windows.
- `ruff check` : 0 remarque ; `pyright` : 0 erreur.

### Versions retenues

Flyway `flyway/flyway:13.12.0` (2026-10-30 ; la 13.12.2 a moins de deux semaines), uv 0.13.8, pytest 9.2.0,
ruff 0.17.5, pyright 1.1.414, fakeredis 2.40.0, scikit-learn 1.9.1, LightGBM 4.7.0, subtr-actor-py 1.5.1.
Actions GitHub : `actions/checkout@v7`, `astral-sh/setup-uv@v10`, `actions/upload-artifact@v7`.

### Problèmes et points ouverts

- Sur le poste Windows, `localhost` dans `RLPI_TEST_DATABASE_URL` bloque (résolu en IPv6, Postgres n'est publié
  que sur `127.0.0.1`) : utiliser `127.0.0.1`.
- Le workflow `Tests` échoue tant que le secret `RLPI_NOMS_INTERDITS` n'est pas créé (voir `REGLAGES_COOLIFY.md`).
- Critères de sortie à constater par Luc : CI verte sur GitHub (après création du secret) et `flyway info` en
  production après la fusion (version 1 en baseline, puis version 2).

## 2026-11-17 — Phase C : découpler le calcul de la configuration globale

Branche `feature/amelioration-logicielle`, un commit par étape.

### Fait

- **`rlpi.context.DataContext`** (`data`, `source`, `ref`, `models`) : les fichiers de la source du joueur sont
  lus dans `data`, ceux des autres sources (RLCS, SSL) dans `ref`, les rapports dans `models`. Passé à
  `make_payload()` et à toutes les sections de `dashboard.py`, à `synergy.run`, `styles.traits` et
  `perf.touch_xv`. Sans contexte (ligne de commande), `DataContext.default()` reprend `config.DATA`,
  `config.SOURCE`, `config.MODELS` : comportement inchangé.
- **Caches** : `_perso_metrics`, `_perso_traits`, `_styles_model`, `_play_seconds` sont indexés par chemin ou
  contexte et date de modification (ns), taille bornée (8 à 32 entrées) ; avant, une seule entrée et une clé
  sans chemin, ce qui n'était juste que dans un sous-processus par joueur.
- **`players.py`** : plus de sous-processus `_inner` ni de `link_reference()`. `build()` rassemble les parties
  puis calcule la synergie dans le processus (`assemble`) ; `payload()` appelle `make_payload` directement. Le
  dossier d'un joueur ne contient plus que ses propres fichiers.
- **Source `theo` renommée `perso`** : défaut de `RLPI_SOURCE`, `rlpi.game merge`, scripts `dev_setup` et
  `make_fixtures` ; commande `decisions touches-theo` retirée. Données locales `rlpi-data-lainox/` renommées
  (`frames/perso/`, `*_perso.*`, accord de Luc). Clés `theo_team_acc` / `theo_n_matches` de `perf_report.json`
  renommées en `perso_*` (jeu d'essai, `rlpi-data-lainox/`) et secours retiré du code ; en production, le
  fichier du volume est à modifier avant la fusion (`REGLAGES_COOLIFY.md`, décidé avec Luc).
- `make_payload` n'écrit plus « référence … » sur la sortie (ces lignes partaient dans le processus fils, elles
  auraient rempli les journaux du serveur).
- Tests : l'instantané passe par l'appel direct ; ajout de « aucun sous-processus » (Popen interdit pendant
  l'assemblage et le calcul) et « deux joueurs dans le même processus » (8 puis 3 parties, caches séparés).
  `context.py` et `players.py` ajoutés à pyright et à `ruff format --check` (CI).

### Décisions

- **Périmètre du contexte** : seul le chemin du tableau de bord (ce que `/moi` calcule) reçoit un
  `DataContext`. Les modules d'entraînement et d'analyse (`decisions`, `value`, `perf.score_source`,
  `bestplay`, `ghost`, `swipe`, `models_page`…) gardent les valeurs de `rlpi.config`, lues à l'import : ce sont
  des commandes, un seul jeu de données par processus. Le worker garde son processus séparé par partie
  (`rlpi.game run`), voulu (isolation, cf. « ce qui va bien » du plan). `config.py` ne contient plus que ces
  valeurs par défaut, le chargement de `.env` et les deux aides ballchasing.

### Vérifications

- Instantané identique octet pour octet, avant comme après le renommage (seul écart vu en cours de route : les
  deux clés de `perf_report.json`, avant leur renommage dans le jeu d'essai). Relancé trois fois : stable sans
  `PYTHONHASHSEED` fixé.
- Jeu d'essai refabriqué par `make_fixtures.py` depuis les données renommées : fichiers identiques.
- Suite complète avec Postgres : 59 réussis, 1 sauté (vrai Flyway, CI seulement) ; ruff 0 remarque ; pyright 0
  erreur.
- `docker-compose.dev.yml` : serveur reconstruit, cache des joueurs vidé, `/moi` après connexion de
  développement : 13,1 s au premier calcul (téléchargement, assemblage, synergie, contenu ; 15,6 s avant), 12 ms
  depuis le cache, 8,3 s pour un filtre de période. Dossier du joueur : uniquement ses fichiers `*_perso`.
  Mémoire du serveur : 137 Mo après ces calculs.
- Worker : `rlpi.game run` sur les replays de `data/raw/` : tous `ok`, étape `perf` comprise sur une partie en
  ligne 3v3.

### Problèmes et points ouverts

- Les calculs tournent maintenant dans les fils du serveur : plusieurs filtres demandés en même temps se
  partagent le processus (Polars libère le GIL pendant ses calculs). Plus de délai maximal de 600 s comme avec
  le sous-processus. Sans conséquence au trafic actuel ; réglé par les agrégats (phase D) et uvicorn (phase E).
- Taille réelle de la phase : S (moins d'une journée), contre M prévu.

## 2026-11-17 — Phase D : agrégats pré-calculés par le worker

Branche `feature/amelioration-logicielle`.

### Fait

- **Migrations** (DB first, vérifications dans la migration elle-même) :
  - `V3__played_at_timestamptz.sql` : `matches.played_at` texte → `timestamptz`, index. Format du replay
    « AAAA-MM-JJ HH-MM-SS » (heure du replay, sans fuseau : enregistrée telle quelle en UTC) ou ISO 8601 de
    ballchasing ; valeur illisible → `RAISE NOTICE` puis `NULL`. Le worker, la recherche ballchasing et
    `dev_setup` écrivent maintenant une date (`store.played_at`).
  - `V4__matches_status_check.sql` : contrainte `CHECK` sur les 7 statuts ; s'il existe un autre statut, la
    migration s'arrête (`RAISE EXCEPTION`, transaction annulée) en listant les parties.
  - `V5__agregats.sql` : `game_aggregates` (une ligne par partie, `jsonb`), `player_game_aggregates` (une ligne
    par joueur et par partie : identité, 35 indicateurs en colonnes `double precision`, `data` lu pour tous les
    joueurs, `details` lu seulement pour le joueur affiché), `reference_aggregates`, `player_versions`.
  - Essayées sur la base locale existante (55 parties, base en V2) : 55 dates converties, aucune illisible.
- **Découpage de `dashboard.py`** (1 025 lignes) en paquet `rlpi/dashboard/`, un module par section : `metrics`
  (critères RLPI, technique, compositions), `value`, `peers`, `passes`, `heat`, `perf`, `synergy`, `style`,
  `advice` (conseils, progression) ; plus `aggregate` (par partie), `reference` (partie fixe), `content`
  (assemblage, filtres, page), `storage` (Postgres), `bootstrap`, `common`. Chaque section a jusqu'à trois
  fonctions : `per_game` (worker), `reference` (une fois), `section` (contenu).
- **Inventaire des sections** (étape 1 du plan) :
  - additives par partie (sommes et comptes) : compositions, passes, cartes de chaleur (grilles), actions des
    touches, ΔV moyen par joueur (synergie) ;
  - comparaisons à une référence fixe : critères RLPI (moyennes par joueur de référence), technique, valeur des
    touches, placement, choix à la touche, groupe « Pros RLCS » des passes, chaleur des pros, synergie SSL,
    rapports des modèles (indice, valeur, styles) → `reference_aggregates` ;
  - non additives, calculées à la volée sur les lignes par partie : moyennes des critères, médianes du lobby,
    rangs, indice (intervalles par tirage), synergie par paire, style, conseils, progression ; pires / meilleures
    touches et passes perdues : les 10 (ou 5) de chaque partie sont gardées, puis départagées.
- **Worker** : après chaque partie traitée, agrégats calculés depuis le dossier local (0,2 s) et écrits ; tâche
  Redis `aggregate` (télécharge `games/<partie>/`) ; au démarrage, un worker (verrou Redis, une fois par heure et
  par version du calcul) met en file les parties sans agrégats à jour ; commande `rebuild-aggregates [--all]
  [--here]`. Un échec du calcul n'annule pas la partie.
- **Serveur** : `/moi` lit les agrégats du joueur (gardés en mémoire tant que sa version de données ne change pas)
  et la référence (relue en base, recalculée au démarrage si ses fichiers ont changé : empreinte tailles + dates).
  Parties pas encore agrégées : « N partie(s) en préparation » dans le bandeau. Clé du cache des pages : version
  des données du joueur + empreinte de la référence (plus la date du fichier de stats).
- **Version des données par joueur** (`player_versions`) : augmentée à chaque partie (re)calculée où il figure ;
  sert au cache du serveur, et servira à l'`ETag` de l'API (phase E).
- `players.py` supprimé (prévu en phase H, mais plus rien ne l'utilise) : plus de téléchargement ni de dossier par
  joueur côté serveur. `game.merge` et `synergy.run` restent pour la ligne de commande.
- `styles.traits` et `perf.touch_xv` séparés de la lecture des fichiers (`traits_from`, `xv`) pour servir partie
  par partie.
- `dev_setup.py` calcule aussi les agrégats des parties qu'il remplit.

### Décisions

- **Références gardées en entier, pas en quantiles** (le plan disait quantiles) : les centiles restent exactement
  ceux d'avant ; taille de la référence locale ≈ 2,9 Mo en base, lue une fois par processus.
- **Ordre des parties conservé** (identifiant de la partie) et **tirages identiques** : les intervalles par
  bootstrap (`rng(0)`) donnent les mêmes valeurs qu'avant. Les tirages ont été vectorisés en reproduisant
  l'algorithme de numpy (flux 32 bits + Lemire, retour à la boucle d'origine en cas de rejet ou si numpy change :
  contrôle au premier usage) — vérifié tirage pour tirage.
- **NaN, ±infini et −0,0** gardés : colonnes `double precision` pour les indicateurs, codage explicite dans les
  `jsonb` (Postgres refuse NaN et perd le signe de −0,0, vu sur les courbes de l'équipe 1).
- Colonne absente des stats d'une partie = valeur vide (comme dans les tables rassemblées d'avant), sauf démos
  et bumps (0, règle existante).
- **Rattrapage automatique** plutôt qu'une commande à lancer en production.
- `won` reste un entier 0/1 (comme dans les stats) : il apparaît tel quel dans le contenu.

### Vérifications

- Instantané du jeu d'essai (5 combinaisons de filtres) : **identique**, en mémoire et après un aller-retour
  Postgres (agrégats et référence écrits puis relus). Chemin de la ligne de commande (dossier rassemblé coupé
  partie par partie) : même contenu.
- Données locales, 4 joueurs (51, 43, 18, 17 parties), 5 combinaisons chacun, contenu calculé par l'ancien code
  avant la refonte comparé au nouveau lu dans Postgres : **0 écart** (nombres à 10 chiffres significatifs).
- Temps (poste, Python 3.13) : lecture des agrégats 25 à 75 ms (une fois par version des données), contenu 50 à
  170 ms ; 204 parties simulées (4 × 51) : ~270 ms. Avant : 3 à 4 s par filtre, 13 à 16 s au premier calcul.
  Page `/moi` complète dans `docker-compose.dev.yml` : 0,57 s la première fois (lecture comprise), ~0,39 s par
  nouveau filtre, 2 ms depuis le cache. Dans ces 0,39 s : ~0,11 s de contenu, ~0,07 s de compression gzip, le
  reste pour sérialiser 1,9 Mo de JSON dans le gabarit (disparaît avec l'API JSON, phases E et F).
- Worker de bout en bout : rattrapage des 55 parties au démarrage (0,3 s par partie, téléchargement compris) ;
  un replay de `data/raw/` retraité : `ok` en 16 s, agrégats en 0,2 s, `played_at` en date.
- Migrations : tests de V3 (formats, fuseau de session sans effet, valeurs illisibles signalées), V4 (statut
  inconnu bloquant, contrainte active), V5 (colonnes = celles écrites par le code).
- Suite : 69 tests (68 réussis, 1 sauté : vrai Flyway, CI seulement) ; ruff 0 remarque ; pyright 0 erreur
  (`rlpi/dashboard` ajouté) ; `ruff format` étendu à `rlpi/dashboard`.

### Problèmes et points ouverts

- La production n'a pas encore d'agrégats : au déploiement, le rattrapage des workers prend environ une seconde
  par partie ; pendant ce temps, le tableau de bord affiche « en préparation » (voir `REGLAGES_COOLIFY.md`).
- Taille réelle de la phase : M (une journée), contre L prévu.

## 2026-11-17 — Phase E : API FastAPI

Branche `feature/amelioration-logicielle`.

### Fait

- **Serveur** : `rlpi.serve` (http.server) et `rlpi.pagecache` remplacés par `src/rlpi/web/` : `main.py`
  (application, journal d'accès, en-têtes de sécurité, `/health`, `/ready`, pages statiques de `RLPI_REPORTS`),
  `settings.py` (pydantic-settings : variables vérifiées au démarrage, noms seuls dans le message d'erreur ;
  refus de démarrer avec `RLPI_DEV_LOGIN=1` en https), `deps.py` (joueur connecté, « chacun ne voit que le sien »,
  contrôle d'origine des écritures), `sessions.py`, `cache.py`, `schemas.py`, `routes/` (`auth`, `api`, `swipe`,
  `legacy`). Image : `uvicorn --factory rlpi.web.main:create_app --workers 2` (`RLPI_WEB_WORKERS`), après les
  migrations comme avant. En local : `python -m rlpi.web`.
- **Routes** : toutes celles du plan. `/api/joueurs/{id}/tableau` reçoit `du`, `au`, `avec`, `sans`, `ref`, et `j`
  (coéquipier affiché, toujours sur les parties du joueur connecté, comme `?j=` avant) ; 403 si `{id}` n'est pas
  le joueur connecté, 401 sans session, 422 pour un paramètre mal formé. Ajout de `POST /api/swipe/deck`
  (demander un paquet). `/docs` décrit 14 routes.
- **Contenu** : `content.dashboard()` (extrait de `content.page()`, inchangé). Réponses mises en cache en mémoire
  (gzip, 64 au plus par processus, un calcul par clé), `ETag` = empreinte du code + version des données du joueur
  + référence + filtres → 304 tant que rien ne change. NaN et ±infini envoyés en `null` (le JSON ne les écrit
  pas ; aucun dans le jeu d'essai).
- **Schémas Pydantic** de tout le contenu (`Contenu` et ses ~60 sous-modèles, `extra="forbid"`), relevés sur
  l'instantané et le code de chaque section ; documentation seulement : le JSON calculé n'est pas revalidé à chaque
  requête. Un test vérifie que les 5 combinaisons de l'instantané y correspondent exactement.
- **Détail d'un match** (`/api/joueurs/{id}/matchs/{match}`) : partie, joueurs, courbe de valeur, indice de
  performance, touches les plus coûteuses et les meilleures, calculés par les sections existantes (`value`,
  `perf`) restreintes à ce match.
- **Sessions révocables** (migration `V6__sessions_swipe.sql`, table `sessions`) : jeton aléatoire de 256 bits dans
  le cookie, seule son empreinte SHA-256 en base ; « dernière utilisation » mise à jour au plus une fois par
  heure ; déconnexion et « déconnexion partout » en POST (formulaires du bandeau et de la page d'import). Ancien
  cookie signé encore valide : accepté et remplacé aussitôt par une session (personne n'est déconnecté au
  déploiement). Retour de Steam sur `/auth/steam/retour` ; `/connexion` et `/connexion/retour` gardés pour les
  connexions commencées pendant le déploiement.
- **Nouveau match traité** : `rlpi.events` ; le worker publie `{"match", "parties"}` sur
  `rlpi:evenements:<joueur>` pour chaque joueur inscrit de la partie, après l'écriture des agrégats (partie
  traitée ou rattrapage). `/api/moi/evenements` relaie (SSE natif de FastAPI : `fastapi.sse`, « ping » toutes les
  15 s au lieu des 30 s du plan, réglage de FastAPI).
- **Les modèles** : `models_page.content()` (données) séparé de `build()` (HTML, ligne de commande) ; fiches omises
  si leur rapport manque (cités dans `absents`) ; corrélation de Spearman calculée par Polars (plus de SciPy, absent
  de l'image du serveur). Relu au plus toutes les 10 minutes.
- **Swipe en ligne** (choix de Luc : worker + lot fixe) : `rlpi.swipe_online`. L'API crée le paquet avec 6 cartes
  SSL et 6 RLCS tirées du lot `<RLPI_DATA>/swipe/reference_cards.json` (`python -m rlpi.swipe pool`, à fabriquer
  sur un poste qui a les replays bruts), puis met une tâche `swipe` en file ; le worker télécharge 8 parties du
  joueur (avec replay brut) et tire 16 cartes « perso », 6 « coéquipiers », 6 « lobbies » (`swipe.player_cards`),
  mélange et donne des identifiants neutres (`<paquet>-<n>`) : ni l'origine ni l'identifiant d'origine (qui
  commençait par `ssl:`…) ne sont envoyés au navigateur. Jugements en base avec l'origine relue dans le paquet.
  `swipe.py` : sous-commandes `deck` (paquet complet hors ligne, comme avant) et `pool`.
- **Transition** : `/moi` sert toujours l'ancien gabarit, mais il ne contient plus de données : un chargeur charge
  `/api/joueurs/{id}/profil` et `/tableau` (script principal passé en `type="module"` pour attendre le chargement),
  message lisible si aucune partie ne correspond aux filtres (avant : page cassée). Plus aucun calcul dans `/moi`.
- Supprimés : `serve.py`, `pagecache.py`, `account.missing/configured` (remplacés par `settings`), le cache de pages
  sur disque (`/app/cache`), `tests/test_serve.py` (remplacé par `tests/test_web.py`, 44 tests).

### Versions retenues

- FastAPI 0.163.2 (Starlette 1.10.0), uvicorn 0.54.0 (`[standard]`), pydantic 2.14.3, pydantic-settings 2.16.3 ;
  httpx 0.28.1 en développement (client de test). FastAPI embarque OpenTelemetry sans exportateur : rien n'est
  envoyé hors du serveur.

### Décisions

- **Vue d'un coéquipier** gardée en paramètre (`j`) de sa propre route plutôt qu'en `/api/joueurs/{coéquipier}` :
  la règle « 403 si ce n'est pas toi » reste simple et sans exception.
- **Paquet swipe** fabriqué par le worker, cartes SSL / RLCS d'un lot fixe (question posée à Luc, réponse :
  « Worker + pool fixe ») : le serveur n'a ni subtr-actor ni les replays bruts des références.
- Configuration manquante : le serveur **refuse de démarrer** (avant : il servait les pages statiques avec un
  message). Toutes les variables existent en production.
- Contenu du tableau de bord renvoyé déjà sérialisé (pas de `response_model` à l'exécution) : le valider à chaque
  requête coûterait plus que son calcul.

### Vérifications

- Suite complète avec Postgres : 88 réussis, 1 sauté (vrai Flyway, CI seulement) ; ruff 0 remarque ; pyright 0
  erreur (`rlpi/web`, `events`, `swipe_online` ajoutés) ; `ruff format` étendu à ces fichiers.
- **Contenu de l'API identique à l'instantané** pour les 5 combinaisons (test `test_tableau_identique_a_l_instantane`,
  agrégats écrits puis relus en base) ; profil identique aux sélecteurs de l'ancienne page.
- `docker-compose.dev.yml` (2 processus uvicorn) : connexion de développement, `/api/moi`, profil, tableau (5
  filtres), match, modèles, 403 / 401 / 404, `If-None-Match` → 304 en 5 à 10 ms. Ancien gabarit affiché dans Edge
  sans fenêtre (piloté par CDP) : page complète, aucune erreur dans la console ; filtre sans partie → message.
- Flux d'événements de bout en bout : replay de `data/raw/` remis en file → partie traitée en 16 s → événement reçu
  21 s après l'ouverture du flux, version des données augmentée.
- Swipe de bout en bout : paquet prêt en 7 s (28 cartes, sans lot de référence en local), aucune origine dans la
  réponse, jugement enregistré avec son origine. `swipe pool` vérifié sur une partie locale déguisée en SSL.
- Temps (premier calcul d'une combinaison, cache ensuite à 10 ms) : sur le poste, contenu 100 à 190 ms +
  sérialisation 30 à 40 ms + gzip 15 ms ; dans Docker Desktop, 180 à 490 ms (le calcul du contenu seul y prend
  250 à 340 ms). gzip passé au niveau 1 (40 ms de moins, réponse ≈ 600 Ko au lieu de 520 Ko pour 1,7 Mo de JSON).
  Mémoire du conteneur : ≈ 280 Mo avec 2 processus après ces requêtes.

### Problèmes et points ouverts

- Objectif de 300 ms (phase D) dépassé dans Docker Desktop au premier calcul d'une combinaison : le coût est dans
  les calculs des sections, non modifiés ici. À mesurer sur le serveur ; sinon, piste en phase F : ne charger que
  l'onglet affiché.
- Le lot de cartes SSL / RLCS n'existe pas encore : à fabriquer sur le poste de Théo (replays bruts RLCS) et à
  déposer dans le volume (voir `REGLAGES_COOLIFY.md`). Sans lui, les paquets ne contiennent que des cartes des
  parties du joueur.
- Le journal d'accès contient l'identifiant Steam dans le chemin des routes `/api/joueurs/{id}/…` (public, pas un
  secret ; jamais de cookie ni de paramètre).
- `starlette.testclient` signale qu'il préfère `httpx2` à httpx : avertissement seulement.
- Taille réelle de la phase : M (une journée), comme prévu.

## 2026-11-17 / 18 — Phase F : interface Vue 3

Branche `feature/amelioration-logicielle`, un commit par étape (socle, un par onglet, Méthode, Les modèles, swipe,
bascule).

### Décisions (Luc, au démarrage)

- **5 onglets du gabarit actuel** (Ma forme, Matchs, Mon jeu, À travailler, Mon trio) + « Tous les indicateurs »,
  pas les 4 de la spec Plateau. Adresses : `/ma-forme`, `/matchs/{partie}`, `/mon-jeu`, `/a-travailler`,
  `/mon-trio`, `/indicateurs`, plus `/modeles` et `/swipe`.
- **Fantôme pro retiré du site** ; pour la même raison (fichiers générés hors ligne pour un seul joueur, servis
  publiquement), le bloc « Le meilleur jeu » d'À travailler et `meilleur_jeu.html` ne sont pas portés.
- **Revue des resets non portée** (fonctionnalité en pause).
- **Image en deux étapes avancée de la phase G** : chaque fusion reste déployable.

### Fait

- **`web/`** : Vite, Vue 3, TypeScript, vue-router (mode historique), vitest. Types de l'API générés depuis
  l'OpenAPI (`scripts/export_openapi.py` puis `npm run api-types` → `web/src/api/schema.d.ts`, versionné ; la CI
  vérifie qu'il est à jour). État partagé sans Pinia (`lib/store.ts`, `lib/ui.ts`).
- **Jetons Plateau importés depuis `Design/`** (une seule copie) : les jetons que l'ancien gabarit avait ajoutés
  (`--on-good`, échelle typographique, tailles intermédiaires, gabarits) sont reportés dans `tokens.css`, ainsi que
  `--scene-*` (légende du swipe) ; `plateau.css` lit les tailles dans les jetons ; plus d'import Google Fonts. Polices
  locales servies comme fichiers à empreinte (cache d'un an) au lieu du base64 dans chaque page.
- **Coquille** : connexion Steam, page d'import qui passe seule au tableau de bord, barre d'onglets (flèches,
  Début/Fin), joueur affiché (`j`), référence (`ref`, mémorisée), bandeau de période ; filtres dans l'adresse,
  appliqués par `fetch`, contenu précédent grisé pendant le calcul ; compte (nouvelles parties, déconnexion) en pied
  de page ; info-bulle commune sans HTML ; panneau Méthode (Échap, focus piégé et rendu au bouton).
- **Onglets portés à l'identique** : texte de chaque onglet, du panneau Méthode (27 674 caractères) et de « Tous les
  indicateurs » comparé à l'ancien gabarit sur les mêmes données (aucune différence) ; captures côte à côte pour Ma
  forme, Matchs et Mon jeu. Graphiques SVG en composants (déroulé, horloge des touches, progression, évolution,
  carte du terrain, barres), redessinés à la largeur réelle (ResizeObserver).
- **Textes** rassemblés dans `web/src/copy/` (verdicts, formulations par indicateur, phrases de lecture, glossaire).
  Gras écrit `**…**` (ou `<b>` dans les rapports de modèles) et rendu par `Rich.vue` sans `v-html` : aucune donnée
  n'est insérée comme HTML.
- **Nouveau match traité** : l'interface écoute `/api/moi/evenements` ; à chaque partie, `/api/moi` puis le contenu
  sont relus (ETag), message « Nouveau match ajouté », filtres gardés. Si le flux est refusé, `/api/moi` chaque
  minute.
- **Les modèles** : page Vue lisant `/api/modeles`. **Swipe** : lecteur canvas repris tel quel en TypeScript,
  habillage Plateau, paquet demandé / préparé par un worker (page mise à jour seule), jugements par l'API (plus
  d'export de fichier), « revoir la précédente », carte remise en place si l'enregistrement échoue.
- **Bascule** : l'interface est servie à la racine (`rlpi.web.spa` : `index.html` pour tout chemin de
  l'application, jamais pour `/api`, `/auth`, `/docs`…) ; `/moi`, `/tableau_de_bord(.html)` → `/ma-forme` (filtres
  gardés), `/v2/…` → même chemin ; connexion et déconnexion reviennent sur `/`. Supprimés : `routes/legacy.py`
  (gabarit, chargeur, formulaire `/moi/actualiser`), le montage des pages statiques et `RLPI_REPORTS`, `web/legacy/`.
- **Image** : étape `node:26.8.1-slim` qui compile `web/` ; CI : types à jour, `vue-tsc`, `vitest`, construction.

### Versions retenues

- Vue 3.5.45, vue-router 5.5.1, Vite 8.3.8, @vitejs/plugin-vue 6.0.11, vitest 5.1.0, @vue/test-utils 2.6.0, jsdom
  31.0.1, vue-tsc 3.3.14, openapi-typescript 7.13.0, Node 26.8.1 (image et CI), actions/setup-node v7.
- **TypeScript 5.9.3, pas 7.0** : openapi-typescript 7.13 exige TypeScript 5.
- `npm audit` : 16 alertes (glob, minimatch, picomatch : déni de service par expressions régulières) dans les outils
  de développement uniquement ; rien n'est livré au navigateur à part vue et vue-router.

### Vérifications

- vitest : 21 tests (formats, phrases de lecture et vues dérivées sur l'instantané du jeu d'essai, glossaire sans
  valeur absente, gras sans HTML) ; `vue-tsc` 0 erreur. pytest : 104 réussis, 1 sauté ; ruff 0 ; pyright 0.
- `docker-compose.dev.yml` : image construite, routes et redirections vérifiées ; flux d'événements de bout en bout
  (replay remis en file → « Nouveau match ajouté » 17 s après, contenu relu avec ses filtres) ; swipe de bout en
  bout (jugement en base avec son origine relue côté serveur).
- **Temps** (Docker Desktop) : premier affichage 0,2 s serveur chaud, 0,8 à 1,0 s quand un processus uvicorn calcule
  la combinaison pour la première fois (lecture des parties du joueur) ; changement de filtre 370 à 430 ms ;
  changement d'onglet 34 ms ; JavaScript 44 Ko compressés.
- Accessibilité : onglets au clavier (flèches, boucle, un seul onglet tabulable), panneau Méthode (Échap, focus),
  carte de fond du swipe inerte, `prefers-reduced-motion` respecté (aussi pour la carte jugée). Pas de défilement
  horizontal à 485 px sur toutes les pages (corrigé : tableau « Qui sert qui », déjà trop large dans l'ancien
  gabarit).

### Écarts et corrections par rapport à l'ancien gabarit

- Bandeau de période : « Appliquer » ignorait la date de fin (instruction prise dans un commentaire) et forçait
  `du` au premier jour ; corrigé (« début » et « aujourd'hui » retirent le filtre).
- Bloc Progression : les lignes « plus fortes progressions / en recul » n'avaient pas leur mise en forme (sélecteur
  `.prog` jamais appliqué) ; elles l'ont maintenant.
- Compte : le bandeau flottant (qui masquait des cartons) devient une ligne en pied de page ; « ← Accueil » retiré
  (plus de page d'accueil statique).

### Problèmes et points ouverts

- Proxy de développement Vite : les écritures vérifient l'origine ; le proxy présente celle de l'API
  (`http://localhost:3001`, comme `RLPI_PUBLIC_URL` de docker-compose).
- `account.py` garde ses pages HTML (connexion, import, bandeau) inutilisées, `dashboard_template.html` et `fonts.py`
  aussi : retrait en phase H, comme prévu.
- Taille réelle de la phase : M (une nuit), contre L prévu.

## 2026-11-18 — Phase H : nettoyage

Branche `feature/amelioration-logicielle`, enchaînée sans pause avec G et I (Luc absent, arrêt impératif avant
5 h).

### Fait

- `serve.py`, `pagecache.py` et `players.py` étaient déjà supprimés (phases D et E).
- **Pages HTML écrites dans des chaînes Python** : supprimées d'`account.py` (connexion, import, bandeau,
  connexion de développement) et de `models_page.py` (page autonome `reports/modeles.html`, `build()`, gabarit CSS
  lu dans l'ancien gabarit). Le serveur ne renvoie plus aucune page HTML à part `index.html` de l'interface.
  - Retour de Steam refusé : redirection vers `/?connexion=echec` (avant : page 403) ; la page de connexion Vue
    affiche « La connexion Steam n'a pas abouti ».
  - Connexion de développement : `GET /dev/joueurs` (JSON, 404 sans `RLPI_DEV_LOGIN=1`) ; la page de connexion Vue
    l'interroge et, s'il répond, propose les joueurs connus. `/dev/connexion` sans joueur renvoie sur `/`. Le
    pseudo est affiché comme texte par Vue (test : `</script><b>x` rendu tel quel dans le JSON).
- **`dashboard_template.html`, `fonts.py`, `dashboard.build()`** supprimés. `python -m rlpi.dashboard --player …`
  écrit le contenu en JSON (`reports/tableau_de_bord.json`, options `--since` et `--until`), utile pour vérifier un
  calcul sans serveur.
- `account.clear_cookie` (ancien cookie signé) retiré ; `make_cookie` / `session_player` restent pour la
  transition des anciens cookies (et les tests qui les fabriquent).
- **Documentation** : README (architecture, interface, installation locale en une dizaine de minutes), `CLAUDE.md`
  (stack réelle au lieu de « à confirmer en phase 0 »), `docs/JOURNAL.md` (conséquences pour le travail sur les
  modèles).

### Vérifications

- pytest 103 réussis, 1 sauté (Flyway réel, CI) ; ruff 0 ; pyright 0 ; vue-tsc 0 ; vitest et construction OK ;
  types de l'API inchangés (les routes `/dev/…` sont hors OpenAPI).
- `docker-compose.dev.yml` (image reconstruite) : `/dev/joueurs` liste les joueurs locaux, retour de Steam annulé →
  303 vers `/?connexion=echec` sans cookie, `/dev/connexion` → `/`. Capture de la page non faite (navigateur de
  test occupé par l'autre session).

### Points ouverts

- Restent volontairement en ligne de commande, hors du site : `rlpi.ghost`, `rlpi.bestplay`, `rlpi.mechanics`
  (revue des resets, avec son gabarit `resets_review_template.html`), `rlpi.swipe pool` (lot de cartes de
  référence).
- `README` : l'installation « sur une machine neuve en 10 minutes » n'a pas été chronométrée sur une machine neuve
  (images déjà en cache sur le poste).

## 2026-11-18 — Phase G : déploiement et exploitation

### Fait

- **Image du serveur en deux étapes** : déjà faite en phase F (Node compile `web/`, l'image Python copie `dist/`).
- **Journaux structurés** (`rlpi.logs`) : une ligne JSON par événement (`ts` UTC, `level`, `service`, `msg`, champs)
  quand `RLPI_LOG_FORMAT=json` (fixé dans les deux images), texte lisible sinon (poste, commandes lancées à la
  main). Uvicorn (`config/journal_uvicorn.json`, formateur `rlpi.logs.JsonFormatter`) et Flyway (chaque ligne
  reprise par `rlpi.migrate`) au même format : plus aucune ligne en texte libre dans les journaux de production.
- **API** : identifiant de requête (`X-Request-ID` repris du proxy s'il est sûr — 8 à 64 caractères
  `[A-Za-z0-9._-]` —, sinon tiré au hasard), renvoyé dans la réponse et ajouté à toute ligne écrite pendant la
  requête (contextvars, y compris depuis les fils de calcul) ; ligne `requête` (méthode, chemin, statut, durée).
- **Worker** : événements avec champs (`match`, `statut`, `duree_s`, `erreur`…) ; toutes les 5 min
  (`RLPI_STATE_MINUTES`), un seul worker (verrou Redis) écrit la ligne `état` : taille de la file, tâches en cours,
  parties « en_cours » depuis plus de 30 min (`warning` s'il y en a), erreurs des dernières 24 h.
- **Sauvegardes** (`rlpi.backup`) : `pg_dump --format=custom` vers Garage (`backups/rlpi-<date>.dump`), planifiée par
  le worker chaque jour à partir de `RLPI_BACKUP_HOUR` (3 h UTC ; une par jour tous workers confondus ; nouvel essai
  une heure plus tard en cas d'échec ; `off` en local). Rétention : 14 derniers jours + première de chacun des
  6 derniers mois. `run`, `list`, `prune`, `restore <clé|latest> --into <URL>` (base cible vide exigée).
  Image du worker : `postgresql-client-18` depuis apt.postgresql.org (Debian n'a que la 17).
- **Documentation** : `docs/DEPLOIEMENT_COOLIFY.md` réécrit (état réel après la refonte : services, variables,
  migrations, sauvegardes et restauration, journaux, opérations courantes, récapitulatif des variables, variables
  obsolètes) ; `docs/REGLAGES_COOLIFY.md` ne garde que les actions ponctuelles de chaque fusion (sections H et G
  ajoutées).

### Décisions

- Sauvegarde faite par le worker plutôt que par les sauvegardes S3 intégrées à Coolify : versionnée et testée avec
  le code, même stockage (Garage), même journal ; la procédure de restauration est la même en local et en
  production. Les sauvegardes Coolify restent une option pour une copie externe plus tard.
- Pas de copie hors du serveur ni d'alerte (décisions du 2026-11-16, rappelées dans la documentation avec les
  pistes pour plus tard : rclone vers R2/B2, Uptime Kuma sur `/ready`).

### Vérifications

- pytest 115 réussis, 1 sauté ; ruff 0 ; pyright 0 (`logs` et `backup` ajoutés à la vérification, et à la mise en
  forme contrôlée par la CI).
- `docker-compose.dev.yml` : images reconstruites ; journaux du serveur et du worker en JSON (Flyway, uvicorn,
  requêtes avec `request_id`, ligne `état`).
- **Essai de restauration** (critère de sortie) : `python -m rlpi.backup run` dans le worker → 2,9 Mo en 0,6 s
  dans Garage ; `restore latest` dans une base neuve `rlpi_restauration` → les 11 tables ont le même nombre de
  lignes que l'original, historique Flyway en version 6 ; nouvelle restauration dans cette base (non vide)
  refusée. `pg_dump` 18.7 dans l'image.

### Versions retenues

- `postgresql-client-18` 18.7 (dépôt apt.postgresql.org, `trixie-pgdg`).

### Problèmes et points ouverts

- Journaux JSON en production non vus (pas d'accès à Coolify depuis le poste) : à contrôler à la fusion
  (`REGLAGES_COOLIFY.md`, phase G).
- Essai de restauration en production à faire par Luc (base à part, sans toucher à la base en service).
- Au passage : les `\` de fin de ligne écrits par l'outil de commandes dans un heredoc étaient perdus (le
  Dockerfile en portait déjà une trace sur la ligne Flyway, sans conséquence) ; les ENV des Dockerfiles ont été
  vérifiés.

## 2026-11-18 — Phase I : worker, après la refonte

### Fait

- **Lettre morte** (migration V7, table `dead_tasks`) : une tâche abandonnée y est écrite avec la tâche telle
  qu'elle était dans la file, la cause, le nombre d'essais et le worker ; ligne de journal `lettre morte`
  (`error`). Concerne : partie encore en erreur après ses 3 essais, agrégats impossibles (après une partie ou en
  tâche `aggregate` ; avant, l'échec n'était repris qu'au prochain rattrapage, c'est-à-dire au redémarrage d'un
  worker), tâche illisible ou de type inconnu (avant : ignorée en silence). Une partie **rejetée** n'y va pas
  (résultat normal). Commandes : `python -m rlpi.worker dead [--all]`, `retry <id> … | --all` (une partie repart
  en `en_attente` avec 0 essai). `status` signale les tâches en attente.
- **Mesures** : `fin de partie` donne `t_replay`, `t_analyse` (avec `etapes`, durées par étape déjà renvoyées par
  `rlpi.game`), `t_envoi`, `t_agregats` ; la ligne `état` ajoute `parties_1h`, `duree_moy_s_1h`, `lettre_morte`
  (et passe en `warning` s'il y a des tâches en lettre morte).
- **Téléchargements Garage en parallèle** : `download_game` télécharge les fichiers d'une partie à plusieurs
  (`RLPI_S3_PARALLEL`, défaut 8, client boto3 partagé entre fils) ; `rebuild-aggregates --here` passe par
  `storage.rebuild` : `--parallel` parties (défaut 3) téléchargées et calculées à la fois, écrites une par une
  dans le fil principal (une connexion Postgres ne se partage pas). Utilisé aussi par le swipe.

### Mesures de la reconstruction complète (55 parties locales, `rebuild-aggregates --all --here`)

| Configuration | Avant | Après |
|---|---|---|
| Conteneur sans limite de CPU (poste, 16 cœurs visibles) | 16,1 s (17 et 16 s au premier relevé) | **9,1 s** (`--parallel 3`), 6,8 s avec `POLARS_MAX_THREADS=2` |
| Conteneur limité à 1,5 CPU (**comme les workers en production**) | 6,9 s | 6,8 s |

- Avant : 4,6 s de téléchargement (691 fichiers) et 11,2 s de calcul, en série.
- Sans limite, Polars lance 16 fils pour de toutes petites tables et se gêne lui-même : la moitié du gain vient
  de là, pas du réseau. Sous la limite de 1,5 CPU, Polars ne prend qu'un fil (il lit la limite du conteneur) et
  la reconstruction est limitée par le calcul : le parallélisme n'y change rien. **Le critère « nettement plus
  rapide » n'est donc rempli que sur une machine sans limite** ; en production, le vrai levier reste
  `rebuild-aggregates` sans `--here`, qui répartit les parties entre tous les workers (×3 avec 3 workers).
- Je n'ai pas fixé `POLARS_MAX_THREADS` dans l'image : en production la limite de CPU fait déjà l'effet.

### Vérifications

- pytest 118 réussis, 1 sauté (dont : partie abandonnée → lettre morte → `retry` ; tâche illisible et inconnue ;
  ligne `état` et durées par étape ; téléchargement parallèle ; reconstruction parallèle) ; ruff 0 ; pyright 0 ;
  instantané du tableau de bord inchangé.
- `docker-compose.dev.yml` (images reconstruites, migration 7 passée par Flyway) : un vrai replay → `fin de
  partie` avec `t_replay` 0,02 s, `t_analyse` 16,2 s (frames 4,6 ; stats 8,0 ; valeur 2,0…), `t_envoi` 0,08 s,
  `t_agregats` 0,2 s ; un fichier corrompu → `rejetee`, pas en lettre morte ; une partie dont le replay manque dans
  Garage → 3 essais puis `lettre morte`, visible dans `dead` et `status`, puis `retry 1` après dépôt du replay →
  `ok`. Parties et fichiers d'essai supprimés ensuite (base locale revenue à 55 parties).

### Points ouverts

- Les parties déjà en `erreur` avant la migration 7 ne sont pas reprises dans `dead_tasks` (rien à importer :
  `status` les liste toujours).
- La lettre morte se consulte en ligne de commande seulement (pas de page d'administration : pas de rôle
  administrateur sur le site).

## 2026-11-20 — Worker : lettres mortes et version du calcul

- Revue de cf5c07e (redéploiement du worker) : le rattrapage périodique sautait toute partie dont le calcul des
  agrégats était en lettre morte, **même après une hausse de `aggregate.VERSION`**. Une nouvelle version qui corrige
  l'échec ne reprenait donc jamais ces parties sans `retry` manuel.
- Migration V8 : colonne `dead_tasks.version` (version du calcul au moment de l'abandon, tâches `aggregate`
  seulement). `storage.missing(skip_dead=True)` ne saute plus que les lettres mortes de la version courante ; les
  lignes antérieures (`version` NULL) sont reprises une fois, puis ré-enterrées avec leur version si elles échouent
  encore.
- Tests : rattrapage avec lettre morte de la version courante, d'une version ancienne et sans version ; un calcul
  abandonné enregistre bien la version. ruff et pyright 0 ; tests Postgres non lancés en local (Docker arrêté),
  à vérifier par la CI.

## 2026-11-20 — Revoir une action en 3D, étape 1 : découpe réutilisable (`docs/PLAN_REVOIR_ACTIONS.md`)

- Nouveau module `rlpi.clips` (sans modèle ni ballchasing, importable par l'API) : `read_replay` (lecture unique
  subtr-actor à 120 Hz), `locate` (instant de la touche à 120 Hz à partir de l'index à 10 Hz et de la balle en
  x, y), `cut` (carte `SwipeCard`, 3 s avant / 1 s après, 30 images/s), plus `world_xy`. `resample` et
  `resample_dir` y sont déplacés.
- `rlpi.swipe.extract` n'est plus qu'une boucle `read_replay` → `locate` → `cut`.
- **Calage en x, y seulement** : vérifié sur les 5 replays de `data/raw/` (passés par `rlpi.game run`) : sur
  1 014 touches, même instant à 120 Hz qu'avec x, y, z dans 100 % des cas, aucune touche écartée.
- **Swipe inchangé** : les 1 014 cartes produites avant et après le découpage sont identiques octet pour octet.
- Lecture d'un replay à 120 Hz sur le poste de Luc : 0,25 à 0,32 s, tableau de 18 à 23 Mo.
- **À savoir pour l'étape 3** : dans `touch_values` (et donc `x`, `y` du tableau de bord), la position de la balle
  est dans le repère de l'équipe du toucheur (équipe 1 : x et y inversés). L'API devra la repasser dans le repère
  du terrain (`clips.world_xy`) avant `locate`.
- Tests : `tests/test_clips.py` (partie fictive : calage, seuil, fenêtre, bornes du clip, voiture absente, balle
  manquante ; vrai replay de `data/raw/`, sauté s'il n'y en a pas : toutes les touches calées, balle du clip au
  moment de la touche cohérente avec les images à 10 Hz, `swipe.extract` passe par `clips`). ruff et pyright 0 ;
  pytest 82 réussis (tests Postgres sautés en local).

## 2026-11-20 — Revoir une action en 3D, étape 2 : index de la touche dans le tableau de bord

- `dashboard/value.py` : les pires et meilleures touches (`touch_rows`) portent `i` (index d'image à 10 Hz) ;
  les touches de la courbe d'un match portent `i`, `x`, `y` (position de la balle, repère de l'équipe du
  toucheur, comme dans `touch_values`).
- Schémas `Touch` et `CurveTouch` (`web/schemas.py`) : `i` obligatoire, `x`, `y` ajoutés à `CurveTouch` ;
  `schema.d.ts` régénéré.
- **`aggregate.VERSION` passe à 2** : le worker recalcule toutes les parties au rattrapage. `load_games` ne lit que
  les agrégats de la version courante : pendant le rattrapage, les parties pas encore recalculées ne s'affichent
  pas (compteur « en préparation »), mais toutes celles qui s'affichent ont `i`. D'où `i` obligatoire, et pas
  besoin de masquer le bouton « Revoir » faute d'`i` à l'étape 4.
- Instantané du tableau de bord mis à jour, différence vérifiée : seuls apparaissent `i` (869 fois), `x` et `y`
  (794 touches de courbe).
- `tests/test_clips.py` (étape 1) remis en forme : il faisait échouer la vérification de format de la CI.
- ruff et pyright 0 ; pytest 82 réussis (tests Postgres sautés en local) ; vue-tsc 0, vitest 21 réussis.

## 2026-11-20 — Revoir une action en 3D, étape 3 : l'appel API `clips`

- `GET /api/joueurs/{id}/matchs/{partie}/clips/{i}` (`web/routes/api.py`) : session et `OwnPlayer` ; la partie
  doit être une des siennes (requête directe sur `match_players`, statut `ok` ou `partiel`), sinon 404. Le
  replay est cherché à la clé `matches.replay_key` (`replays/<partie>.replay` à défaut). Côté interface,
  l'identifiant de partie est le `replay` des touches : c'est le même que l'identifiant du match (le worker
  analyse le fichier `<partie>.replay`).
- Nouveau module `rlpi.web.clips` (`ClipService`) : télécharge d'abord `meta.json` et `touch_values` (quelques Ko),
  cherche la touche `i` (inconnue → 404 sans télécharger le replay), puis le replay, `read_replay` → `locate` →
  `cut`. La position de la balle de `touch_values` est repassée dans le repère du terrain (`clips.world_xy`).
- **Deux touches dans la même image à 10 Hz** (deux joueurs) : on prend celle du joueur connecté, sinon la
  première. L'auteur de la touche est la voiture mise en avant (un coéquipier affiché par le filtre « joueur »
  est donc bien mis en avant sur ses propres touches).
- Protection : route synchrone (pool de threads) ; au plus 2 lectures de partie en même temps (sémaphore) ;
  verrou par partie (deux clics simultanés sur le même match = une lecture) ; dernière partie lue gardée en
  mémoire ; clips gardés en gzip dans un LRU de 300 entrées (environ 6 Mo).
- ETag `"clip-…"` (partie, `i`, `rlpi.web.clips.VERSION`), indépendant de l'empreinte du code ; `Cache-Control:
  private, max-age=86400` puis revalidation (pas `immutable` : l'URL ne change pas si la découpe change).
- Erreurs : 404 « Replay non conservé pour cette partie. », 404 « Touche inconnue dans cette partie. », 404
  « Données de la partie introuvables dans le stockage. », 422 « Impossible de retrouver cette touche dans le
  replay. », 422 « Touche trop près du début ou de la fin du replay pour en faire un clip. ».
- Schéma `Clip` (`web/schemas.py`, format `SwipeCard` plus `id` = `<partie>:<i>`) ; `schema.d.ts` régénéré.
- `subtr-actor-py==1.5.1` ajouté à l'extra `server`, `uv.lock` à jour. Image du serveur reconstruite : 1,23 →
  1,24 Go. Dans le conteneur : lecture d'un replay 0,20 à 0,26 s (5 replays de `data/raw/`), pic mémoire
  +58 Mo pour une lecture (89 Mo contre 31 Mo) ; avec 2 lectures simultanées et la dernière partie gardée
  (environ 20 Mo), compter environ 150 Mo de plus pour l'API au pire.
- Mesure locale du service sur un vrai replay (1,7 Mo, 198 touches) : 198 clips sur 198, premier clic 0,45 s
  (téléchargement compris), clics suivants sur le même match 92 ms en médiane (174 ms au plus) ; clip de 20 Ko
  en gzip (57 Ko brut).
- Tests (`tests/test_web.py`) : service sur la partie fictive de `test_clips` (calage dans le repère du terrain,
  touche du joueur connecté préférée, auteur mis en avant, dernière partie gardée, 404 / 422), stockage
  incomplet (replay absent, touche inconnue sans lecture du replay, partie absente), vrai replay de `data/raw/`
  (sauté s'il n'y en a pas), route : 401, 403, 404 (pas sa partie, partie inconnue, touche inconnue, replay
  supprimé), 422, 200 en gzip, 304 sur l'ETag, clic suivant servi sans relire le replay.
- ruff et pyright 0 ; pytest 135 réussis avec Postgres local (`docker-compose.dev.yml`) ; vue-tsc 0.
- **Tests Postgres sous Windows** : `RLPI_TEST_DATABASE_URL` doit viser `127.0.0.1` et pas `localhost`. Avec
  `localhost`, la connexion à la base de test toute neuve reste bloquée sans erreur (Docker n'écoute que sur
  `127.0.0.1`, `localhost` est d'abord résolu en `::1`).

## 2026-11-20 — Revoir une action en 3D, étape 4 : le lecteur dans l'interface

- `web/src/lib/clips.ts` : `loadClip(partie, i) → Promise<SwipeCard>`, seul endroit qui sait d'où vient le clip
  (l'API, route de l'étape 3, joueur connecté). Garde les 40 derniers clips demandés en mémoire (un échec n'est
  pas gardé : le clic suivant réessaie). Messages en français : celui de l'API pour les 404 / 422 (« Replay non
  conservé pour cette partie. »…), sinon session expirée, clip pas préparé ou serveur muet.
- `web/src/components/ActionReplay.vue` : une seule fenêtre pour toute l'application (montée dans `App.vue`,
  état partagé `lib/replay.ts`, comme le panneau Méthode). `<dialog>` natif en modal : focus gardé dedans, Échap,
  clic à côté ou « Fermer » ; le focus revient au bouton « Revoir » après la fermeture. Lecteur
  `swipe/player.ts` sans modification : lecture / pause, recommencer, ×1 / ×0,5 / ×0,25, barre de temps avec le
  repère jaune de la touche, rotation, vue de dessus ; en-tête « Dégagement · 2:31 · situation −0,30 → −0,60 »
  et date ; ligne « Reconstitution 3D à partir du replay, pas une vidéo du jeu ». États chargement (avec « le
  premier clip d'un match prend environ une seconde ») et erreur (message de l'API, « Réessayer »).
  `prefers-reduced-motion` : pas de lecture automatique, le clip s'ouvre arrêté sur la touche.
  Plein écran sous 720 px, boutons d'au moins 40 px.
- `web/src/components/ReplayButton.vue` (« ▶ Revoir ») : À travailler (3 fiches, à côté de « Ouvrir le match »,
  et chaque ligne des suivantes : la ligne n'est plus un seul bouton, le bouton « Revoir » est à côté) ; Matchs
  (chaque ligne de « Les actions qui coûtent »). Absent sans partie, sans indice d'image ou sans joueur connecté.
- Contrôles du lecteur : styles communs à la carte du Swipe et à la fenêtre (`app.css`). Retrait d'un
  `cursor: pointer` resté sur les lignes de « Les actions qui coûtent » (elles n'étaient pas cliquables).
- Textes dans `copy/index.ts` (`REVOIR`, `replayTitle`, `replayLabel`) ; rubrique « Revoir une touche en 3D » dans
  le panneau Méthode (`copy/glossary.ts`).
- Tests vitest : `lib/clips.test.ts` (adresse appelée, mémoire, messages d'erreur, réessai après échec),
  `components/ReplayButton.test.ts` (affichage conditionnel, ouverture sur la bonne touche sans déclencher la
  ligne, titre). vue-tsc 0 ; vitest 31 réussis ; construction OK.
- Vérifié à la main (`docker-compose.dev.yml`, agrégats recalculés en version 2 par `rebuild-aggregates --here`,
  55 parties en 11 s) : À travailler et Matchs, premier clip 1,1 s (relecture du replay comprise), clip suivant
  du même match ≈ 0,95 s mesuré dans le navigateur ; partie sans replay → « Replay non conservé pour cette
  partie. » ; Échap, clic à côté, retour du focus ; mobile 390 px avec `prefers-reduced-motion`.
- Remarqué au passage, non corrigé (hors périmètre) : sur mobile (390 px), le bandeau du résultat de l'onglet
  Matchs (`.resultbar`) dépasse de 16 px à droite et fait défiler la page en largeur.

## 2026-11-20 — Revoir une action : vue joueur

- Demande de Théo : voir la touche depuis la caméra du joueur. Le replay contient, pour chaque joueur, ses
  réglages caméra (FOV, distance, hauteur, angle, raideur) et chaque bascule caméra balle / caméra voiture
  (`subtr_actor.get_replay_frames_data`, subtr-actor-py 1.5.1 : `meta.team_*[].camera_settings` et
  `player_camera_events`). Le swivel (stick droit) n'est presque pas enregistré (yaw/pitch caméra à 128 sur
  99,5 % des images d'un replay testé) : il n'est pas relevé.
- Cette lecture est lourde (1,5 à 3 s, environ 260 Mo en Python) : `rlpi.clips.read_cameras` est appelée une fois
  par le worker (nouvelle étape `cameras` de `rlpi.game`, fichier `frames/partie/<replay>.cameras.json`, environ
  9 Ko, envoyé sur Garage avec le reste). Pour les parties analysées avant, l'API la fait une fois au premier clip
  puis dépose le fichier ; en cas d'échec, le clip part sans caméra.
- Clip : champ `cam` (réglages, `known`, caméra balle 0/1 à chaque image), calé sur le temps du replay (colonne
  `CurrentTime` ajoutée à `read_replay`). Version des clips 1 → 2 (ETag). Cartes du Swipe inchangées.
- Lecteur (`swipe/player.ts`) : mode `pov` en perspective. Caméra derrière l'auteur à `distance`/`height`, tournée
  vers la balle (inclinaison bornée) ou dans l'axe de la voiture (`angle`), suivi lissé selon la raideur ; FOV
  horizontal en 16:9, champ vertical gardé sur les autres formats. Coupure au plan proche des polygones et
  segments, faces des voitures cachées selon la position de la caméra, voitures à taille réelle, murs voilés.
  Réglages par défaut du jeu (110 / 270 / 100 / −3 / 0,5) quand la caméra n'est pas relevée.
- Fenêtre « Revoir » : bouton « Vue joueur » (choix gardé d'un clip à l'autre ; rotation et vue de dessus
  désactivées dans ce mode), bandeau « caméra balle » / « caméra voiture », note sur l'origine des réglages.
- Tests : `test_clips` (caméras dans la découpe, vrai replay), `test_web` (caméra dans le clip, calcul unique et
  dépôt du `cameras.json`). pytest 88 réussis ; ruff OK ; vue-tsc 0 ; vitest 31. Rendu vérifié sur 3 touches
  d'un vrai replay (caméra balle au sol, aérien en caméra voiture). L'erreur pyright de `game.py:62` existait déjà.

## 2026-11-20 — Revoir une action : corrections après relecture

- Étape `cameras` de `rlpi.game` : un échec n'est plus une erreur (la partie ne passe plus « partiel ») mais un
  avertissement dans `result.json` (`warnings.cameras`) ; le clip part alors sans caméra.
- Clips toujours à jour : l'ETag, le cache des clips et la partie gardée en mémoire portent la version de la
  partie (`matches.updated_at`, changée à chaque traitement). Une partie réanalysée n'est plus servie périmée
  (avant : jusqu'à 24 h côté navigateur, sans limite côté serveur).
- L'ETag dépend aussi du joueur connecté (sa touche est préférée quand deux joueurs touchent la balle dans la même
  image).
- Tests : `test_clip_service_partie_reanalysee`, et `test_clip_api` vérifie le nouvel ETag après réanalyse. Tests
  clips (Postgres compris) réussis ; ruff OK.

## 2026-11-20 — Revoir une action : route asynchrone, verrous par clé

- Route des clips en `async def` : un clip déjà gardé est servi sans attendre (`ClipService.aclip`) ; les autres
  sont faits dans un thread, au plus `MAX_READS` = 2 à la fois (`anyio.CapacityLimiter`, qui remplace le
  sémaphore). Les demandes en trop attendent leur tour sans occuper l'un des 40 threads du serveur, et un clip
  gardé ne fait plus la queue derrière une lecture lente. La requête Postgres de la route passe dans un thread.
- Verrous par clé (`cache.KeyedLocks`, utilisé par `JsonCache.compute` et par les parties de `ClipService`) : le
  verrou n'est retiré que quand plus personne ne le tient ni ne l'attend. Avant, une demande arrivée pendant
  qu'une autre attendait recevait un nouveau verrou et calculait en parallèle (cas d'un calcul qui échoue, donc
  non gardé, avec trois demandes ou plus).
- Tests (écrits d'abord, en échec avant le correctif) : `test_cache_un_seul_calcul_a_la_fois_meme_apres_un_echec`,
  `test_clip_service_async_clip_garde_servi_pendant_une_lecture`. pytest 140 réussis (Postgres compris) ; ruff
  OK ; pyright `rlpi.web` 0 erreur.

## 2026-11-20 — Revoir une action : caméras rattrapées par le worker

- Le serveur web ne lit plus jamais les caméras dans le replay (environ 250 Mo par lecture, deux possibles en même
  temps) : sans `cameras.json`, le clip part sans caméra (réglages par défaut du jeu dans le lecteur).
- `python -m rlpi.worker backfill-cameras` : pour chaque partie `ok`/`partiel` sans `cameras.json`, télécharge le
  replay et lit les caméras dans un processus séparé (`rlpi.game.cameras`, sous-commande `_cameras`), une partie à
  la fois, puis dépose le fichier. Parties sans replay gardé ou au replay illisible : comptées et passées. Sans
  risque à relancer. Commande à lancer une fois après la fusion (`docs/REGLAGES_COOLIFY.md`).
- Tests (écrits d'abord, en échec avant le correctif) : `test_rattrapage_cameras` (worker),
  `test_cameras_dans_un_processus_separe` (vrai replay de `data/raw/` comparé à la lecture directe, replay abîmé
  → erreur sans fichier), `test_clip_service_sans_cameras` ; `synthetic_replay` refuse toute lecture des caméras
  côté web. pytest 143 réussis (Postgres compris) ; ruff OK.
