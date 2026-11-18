# Plan de refonte de l'application web RLPI

Ce plan couvre **l'application web et son exploitation** : serveur, API, interface, base de données, file
d'attente, déploiement. Il ne touche pas aux modèles ni au calcul des indicateurs (`docs/PLAN.md`) : les chiffres
affichés doivent rester **identiques** avant et après la refonte.

Chaque phase a un livrable et des critères de sortie.

**Façon de travailler** (décidé le 2026-11-16) : un commit par étape logique (par exemple un par onglet en
phase F), fait par Claude, sur la branche `feature/amelioration-logicielle`, poussée sur GitHub (dépôt privé).
La fusion dans `main` (donc la mise en production) est faite par Luc. Claude s'arrête à la fin de chaque phase
pour que Luc lance `/compact` avant la suivante.
Tout réglage à faire à la main dans Coolify est noté, au fil des phases, dans `docs/REGLAGES_COOLIFY.md`. C'est Luc
qui les applique (accès Coolify et SSH, confirmé le 2026-11-17).
Le suivi de la refonte (date, ce qui est fait, décisions, versions retenues, problèmes) est tenu dans
`docs/JOURNAL_REFONTE_WEB.md`, à part du journal des modèles (`docs/JOURNAL.md`).

**Données de travail** : le dossier `rlpi-data-lainox/` (non versionné, à ajouter au `.gitignore` avant tout
commit) contient `features/`, `frames/` (`rlcs/`, `theo/`), les rapports des modèles (`models/*.json`, sans les
modèles LightGBM `.txt`) et les pages écrites à la main de `reports/`. Il sert de source au jeu d'essai (phase B).
Contenu précisé le 2026-11-17 : `frames/theo/` (environ 65 parties) et `*_theo.parquet` ne contiennent que des
parties **où Théo joue** ; Rileq ou LAinox y figurent parfois, jamais sans Théo. `frames/rlcs/` sert de référence.
Les modèles `.txt` utilisés par le worker sont dans `models/` à la racine du dépôt. Cinq vrais replays
(`data/raw/*.replay`, non versionnés) servent à faire tourner le worker de bout en bout en local.
Taille indicative de chaque phase : S (≤ 1 jour), M (2 à 4 jours), L (≥ 1 semaine). Ce sont des ordres de
grandeur, à revoir après la phase C.

---

## 1. Où on en est

### Architecture actuelle

```
Navigateur ──GET /moi?du=…&avec=…──► serve.py (http.server de Python, routes écrites à la main)
                                       │
                                       ├─ players.build()  : Postgres + téléchargement Garage + fusion Parquet
                                       ├─ sous-processus Python n°1 : synergie
                                       ├─ sous-processus Python n°2 : make_payload() (Polars, lit tout)
                                       ├─ JSON collé dans dashboard_template.html (1 492 lignes, HTML+CSS+JS)
                                       │  + 4 polices en base64 (~160 Ko) dans chaque page
                                       └─ PageCache : page HTML complète en mémoire + sur disque
Navigateur ◄── page complète (3 à 9 s si pas en cache) ; chaque filtre = nouvelle page complète

Worker(s) : Redis (file) → rlpi.game run → Garage (games/<partie>/) → Postgres (matches, match_players)
```

### Ce qui va bien et qu'on garde

- La chaîne du worker : file Redis fiable (`BLMOVE` vers une liste « en cours », reprise au redémarrage,
  3 tentatives, détection des doublons par GUID), traitement partie par partie dans un processus séparé.
- Postgres, Redis et Garage comme socle, sur Coolify.
- La connexion Steam (OpenID 2.0 avec `check_authentication`) et le cookie de session signé HMAC.
- Le design system Plateau (`Design/rlpi-plateau/`) : jetons, composants et architecture en 4 onglets déjà écrits.
- Le déploiement automatique GitHub Actions → ghcr.io → Coolify.

### Ce qui pose problème

| # | Problème | Où | Conséquence |
|---|---|---|---|
| P1 | La page web **est** le calcul : pas d'API, chaque combinaison de filtres produit une page HTML complète | `serve.py`, `dashboard.py` | 3 à 9 s par filtre, pré-calcul et cache de pages à maintenir |
| P2 | Le calcul lourd tourne **dans la requête HTTP** (téléchargements, fusion, 2 sous-processus, délai max 600 s) | `players.py:163`, `serve.py:98` | Le visiteur attend, le serveur sature vite |
| P3 | Configuration figée à l'import (`DATA`, `FEATURES`, `SOURCE` globaux) | `config.py` | Impossible de calculer pour un autre joueur dans le même processus → sous-processus + liens symboliques |
| P4 | Verrous et cache dans le processus, fils de requête sans limite, calcul Polars dans ces fils | `serve.py`, `pagecache.py` | Une seule instance possible, pas de montée en charge |
| P5 | Nouvelle connexion Postgres **et** exécution du schéma (`CREATE`/`ALTER`) à chaque appel | `store.py:94` | Lenteur, pas de migrations versionnées |
| P6 | JSON inséré dans `<script>` sans échapper `<` ; nombreux `innerHTML` | `serve.py:79`, `serve.py:108`, gabarit | Faille XSS probable via un pseudo de joueur (choisi librement) |
| P7 | Frontend : un fichier de 1 492 lignes, état global, rendus manuels, rechargement complet à chaque filtre | `dashboard_template.html` | Difficile à faire évoluer, à tester, à sécuriser |
| P8 | Dépendances en double et divergentes (`pyproject.toml` ≠ Dockerfiles), rien de verrouillé | `pyproject.toml`, `Dockerfile*` | Images non reproductibles ; `subtr-actor-py` absent de `pyproject.toml`, Streamlit déclaré mais inutilisé |
| P9 | Aucun test ; la CI déploie à chaque push sur `main` sans vérification | `.github/workflows/deploy.yml` | Une régression part directement en production |
| P10 | Journaux d'accès coupés, pas de mesure des temps de réponse | `serve.py:165` | Panne ou lenteur invisibles |
| P11 | Pages écrites à la main dans `reports/`, dossier **non versionné** (accueil, swipe…) | `reports/` | Perte possible, pas d'historique |
| P12 | Code mort ou en double : `dashboard_template_v1.html`, pages de compte en chaînes Python | `account.py` | Bruit, confusion |
| P13 | Joueurs écrits en dur : identifiant Steam de Théo et coéquipiers (`LAinox,Rileq`) par défaut, `RLPI_PLAYER` / `RLPI_COMPARE` lus à l'import par `serve`, `styles`, `swipe`, `dashboard`, source de données nommée `theo` | `config.py:27-34`, `serve.py:40,133-143,258`, `styles.py:21`, `swipe.py:27-28`, `players.py:142` | Le code suppose un joueur principal ; données personnelles dans le dépôt |

---

## 2. Cible

```
                         ┌──────────────────────── Coolify ────────────────────────┐
Navigateur               │                                                          │
  Vue 3 (SPA statique) ──┼─► FastAPI (uvicorn, 2+ processus)                        │
  /api/... en JSON  ◄────┼──   ├─ lit des agrégats déjà prêts (quelques ms à 300 ms) │
                         │     ├─ pool Postgres, client Redis partagé                │
                         │     └─ sert aussi les fichiers du frontend (cache long)   │
                         │                                                          │
                         │  Worker(s) : Redis → analyse de la partie → Garage        │
                         │              └─► NOUVEAU : agrégats par partie et joueur  │
                         │                  écrits en base (lus par l'API)          │
                         │  Postgres (comptes, parties, agrégats)   Redis   Garage  │
                         └──────────────────────────────────────────────────────────┘
```

Le principe : **le worker calcule, l'API sert, le navigateur affiche.**

### Choix techniques

| Couche | Choix | Pourquoi |
|---|---|---|
| Langage serveur | **Python** (inchangé) | Toute la chaîne de données est en Python ; un autre langage obligerait à maintenir deux piles |
| Framework web | **FastAPI** + **uvicorn** | Routes typées, validation Pydantic, documentation OpenAPI automatique (`/docs`), plusieurs processus |
| Accès Postgres | **psycopg 3** + **psycopg_pool** ; requêtes SQL écrites à la main (pas d'ORM) | Pool ouvert au démarrage ; le schéma n'est plus exécuté à chaque connexion |
| Migrations | **Flyway**, en « DB first » (décidé le 2026-11-16) : le schéma est défini par des fichiers SQL versionnés (`migrations/V1__schema_initial.sql`, `V2__…`), jamais généré depuis le code Python | Historique des changements de schéma dans la base (`flyway_schema_history`), verrou contre les exécutions simultanées, sommes de contrôle sur les migrations déjà passées |
| Configuration | **pydantic-settings** | Variables d'environnement validées une fois, au démarrage ; plus de valeurs en dur |
| Frontend | **Vue 3** + **Vite** + **TypeScript** + **vue-router** | Affichage réactif, échappement par défaut (fin des XSS par `innerHTML`), composants alignés sur Plateau |
| État frontend | `ref`/`reactive` partagés (pas de Pinia au départ) | L'état se résume aux filtres, au joueur, à la référence et à l'onglet |
| Graphiques | SVG faits main, transformés en composants Vue | Ils suivent déjà la charte Plateau ; une librairie imposerait son style |
| Types partagés | **openapi-typescript** : types TS générés depuis l'OpenAPI de FastAPI | Le contrat API ↔ interface est vérifié à la compilation |
| Dépendances | **uv** avec `uv.lock` ; extras `server`, `worker`, `dev` | Une seule source de vérité, images reproductibles |
| Qualité | **ruff** (lint + format), **pytest**, **pyright** (progressivement) ; **vitest** et **vue-tsc** côté interface | Tests automatiques avant tout déploiement |

---

## 3. Phases

### Phase A — Corrections immédiates (S)

**Objectif** : sécuriser et assainir l'existant, sans changer l'architecture.

- **Au début de la phase** : création de `docs/JOURNAL_REFONTE_WEB.md` et de `docs/REGLAGES_COOLIFY.md` (ils
  n'existent pas encore, constaté le 2026-11-17).

- ~~**Avant tout** : `rlpi-data-lainox/` ajouté au `.gitignore` (vrais pseudos et identifiants Steam).~~ Fait le
  2026-11-17.
- **Environnement local d'abord** (avancé de la phase B, décidé le 2026-11-16) : `docker-compose.dev.yml` avec
  Postgres, Redis, **Garage** comme stockage S3 (décidé le 2026-11-17 : même outil qu'en production), le serveur
  et le worker. Il sert à vérifier les corrections de cette phase dans un vrai environnement multi-joueurs
  (jamais testé en local jusqu'ici, journal du 2026-11-15). Le service Flyway s'y ajoute en phase B. `uv` et
  Docker Desktop sont déjà installés sur le poste (2026-11-17).
  - **Versions** : Postgres **18** (la production est en 18.7, vu dans le `pg_dump` du 2026-11-17), Garage
    `v2.3.0` (comme en production, `DEPLOIEMENT_COOLIFY.md`).
  - **Remplissage** (décidé le 2026-11-17) : un script charge les parties de `rlpi-data-lainox/` dans Postgres et
    Garage, sans passer par ballchasing (pas d'appel à l'API). Il prépare aussi le jeu d'essai de la phase B.
    Les Parquet de `rlpi-data-lainox/` sont déjà fusionnés : le script les **découpe partie par partie** pour écrire
    dans Garage (`games/<partie>/`) et dans `matches` / `match_players` exactement ce que le worker aurait produit.
  - **Worker de bout en bout** (2026-11-17) : les 5 replays de `data/raw/` sont envoyés dans la file locale pour
    vérifier toute la chaîne (Redis → `rlpi.game run` → Garage → Postgres) avec les modèles de `models/`.
    Ces replays ne font pas partie de `rlpi-data-lainox/` (confirmé par Luc le 2026-11-17) : ils peuvent être
    envoyés après le remplissage sans être pris pour des doublons.
  - **Ballchasing en local** (décidé le 2026-11-17) : le serveur et le worker locaux reçoivent le vrai
    `BALLCHASING_TOKEN` du `.env`, pour pouvoir tester la recherche de nouvelles parties (connexion, bouton
    « actualiser ») de bout en bout. Les limites de débit de l'API s'appliquent comme en production ; seul le
    script de remplissage n'appelle jamais ballchasing.
  - **Poste Windows** : `uv` et `pytest` tournent directement sur le poste ; Postgres, Redis, Garage, le serveur
    et le worker dans Docker. La CI (phase B) tourne sous Linux.
  - **Connexion de développement** (décidé le 2026-11-17) : une route qui ouvre une session pour n'importe quel
    joueur sans Steam, active seulement si `RLPI_DEV_LOGIN=1`. Le serveur refuse de démarrer si cette variable
    est active alors que `RLPI_PUBLIC_URL` est en `https://` (production). Elle sert à tester « chacun ne voit
    que le sien » avec plusieurs joueurs. Comme toutes les parties locales contiennent Théo, ce test n'est fait
    que dans la mesure du possible (Rileq ou LAinox sur leurs quelques parties) ; s'il n'est pas concluant en
    local, on le laisse de côté (accepté le 2026-11-17).
- **XSS** : échapper `<`, `>` et `&` du JSON inséré dans le gabarit (`json.dumps(...).replace("<", "\\u003c")`…).
  Relire chaque `innerHTML` du gabarit : toute valeur venant des données (pseudos surtout) passe par `esc()`.
- **Postgres** : un pool de connexions (`psycopg_pool`) créé au démarrage ; le schéma exécuté une seule fois au
  démarrage (serveur et worker), plus à chaque `store.db()`. `psycopg_pool` est ajouté dès cette phase,
  directement dans `pyproject.toml` et dans les deux Dockerfiles (décidé le 2026-11-17) ; la remise à plat des
  dépendances avec `uv` reste en phase B.
- **Journaux d'accès** rétablis (méthode, chemin, statut, durée), sans cookie ni paramètre sensible.
- **Compression** : envoyer directement la page gzip du cache (`Content-Encoding: gzip`) quand le navigateur l'accepte.
- **En-têtes de sécurité** : `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `X-Frame-Options: DENY`.
- **POST /moi/actualiser** : vérifier l'en-tête `Origin` (protection CSRF en plus de `SameSite=Lax`). L'origine
  attendue est lue dans la variable existante `RLPI_PUBLIC_URL` (`https://rlpi.lainox.quest` en production,
  vérifié le 2026-11-17 dans `account.py` et `docs/DEPLOIEMENT_COOLIFY.md`) ; aucune nouvelle variable.
- Supprimer `dashboard_template_v1.html`.
- **Suppression du mode local** (décidé le 2026-11-17, remplace « mis de côté ») : `app.py` (application tkinter)
  et ce qui ne sert qu'au kit de lancement local (scripts d'installation, partie « kit de lancement » du README)
  sont supprimés dès cette phase. `dashboard_template.html`, `fonts.py` et `dashboard.build()` restent tant que
  `/moi` s'en sert ; ils partent en phase H. `autoupload.py` n'en fait pas partie : il alimente ballchasing, donc
  le site, et il est gardé.
- **Plus de tableau de bord public** (décidé le 2026-11-16, voir § 5) : `/tableau_de_bord.html` et `/tableau_de_bord`
  redirigent vers `/moi` (connexion Steam obligatoire). Cela ferme aussi la consultation des autres profils par
  `?j=`. Retirer le pré-calcul des pages publiques (`warm_defaults`).
- **Plus aucun joueur en dur** (décidé le 2026-11-17) : le code ne connaît plus de « joueur principal ».
  - Suppression de `RLPI_PLAYER` et `RLPI_COMPARE` (et de leurs valeurs par défaut : identifiant Steam de Théo,
    `LAinox,Rileq`) dans `config.py`, `serve.py` et `.env.example` (`app.py` est supprimé, voir plus bas).
  - Serveur : plus d'inscription automatique ni de synchronisation au démarrage d'un joueur fixé, plus de liste
    `PLAYERS` ; le joueur affiché est toujours celui de la session. Théo se connecte par Steam comme tout le monde
    (il l'a déjà fait une fois en production : son compte existe, confirmé le 2026-11-17). Comme tout compte
    inscrit, ses nouvelles parties continuent d'être cherchées automatiquement par les workers (toutes les 15 min),
    en plus de sa connexion et de l'actualisation à la demande ; seul le pré-calcul de sa page par le serveur
    disparaît (accepté le 2026-11-17).
  - `styles.py` (`ME`) et `swipe.py` (`PERSO`, `PEERS`) reçoivent le joueur et ses coéquipiers en paramètre au
    lieu de les lire à l'import.
  - Commandes en ligne (`dashboard`, `bestplay`, `ghost`) : `--player` obligatoire, sans valeur par défaut.
  - Exemples d'aide et commentaires : identifiants fictifs (`Steam:7656119800000000x`) au lieu de celui de Théo.
  - Restent : `RLCS_REFEREE` dans `collect.py` (compte qui publie les replays RLCS, pas un joueur suivi) et le
    nom de source `theo` des fichiers de données, renommé en phase C.
  - Si `RLPI_PLAYER` / `RLPI_COMPARE` sont définis dans Coolify, les retirer (noté dans `REGLAGES_COOLIFY.md`).

**Sortie** : un pseudo de test `</script><b>x` s'affiche tel quel, sans casser la page ; une page servie depuis le
cache ne déclenche plus aucune connexion Postgres supplémentaire ; sans cookie, `/tableau_de_bord.html` renvoie
vers la connexion et aucun contenu de tableau de bord n'est servi ; `grep` de `76561198078330309`, `LAinox`,
`Rileq`, `RLPI_PLAYER` et `RLPI_COMPARE` dans `src/` ne renvoie plus rien ; tout est vérifié dans
`docker-compose.dev.yml`.

---

### Phase B — Socle qualité (M)

**Objectif** : pouvoir modifier le code sans peur de casser la production.

1. **Dépendances** : `uv` + `uv.lock` ; extras `server` (FastAPI, uvicorn, psycopg, redis, boto3, polars…),
   `worker` (+ LightGBM, scikit-learn, subtr-actor-py, python-ballchasing), `dev` (pytest, ruff, pyright).
   Retirer Streamlit. Les Dockerfiles font `uv sync --frozen --extra server` (ou `worker`).
2. **Environnement de développement local** : `docker-compose.dev.yml` créé en phase A ; on y ajoute ici le
   service Flyway (point 7).
3. **Jeu de données d'essai** (accepté le 2026-11-16) : 5 à 10 vraies parties (Parquet, quelques Mo) tirées de
   `rlpi-data-lainox/` et versionnées dans `tests/fixtures/`, plus des références SSL/RLCS réduites. Pseudos et
   identifiants Steam remplacés par des valeurs fictives, de façon cohérente d'une partie à l'autre (un même
   joueur garde le même faux identifiant). Vérifier au début de la phase que `make_payload()` n'a besoin d'aucun
   modèle LightGBM `.txt` (absents de `rlpi-data-lainox/models/`).
4. **Tests** :
   - **instantané du contenu du tableau de bord** : `make_payload()` sur le jeu d'essai, comparé à un fichier de
     référence. Ce test est **le garde-fou de toute la refonte** : les chiffres ne doivent pas bouger ;
   - session (cookie valide, expiré, falsifié), vérification Steam (réponse simulée), routes principales ;
   - worker : traitement d'une tâche simulée (file, statuts, reprise).
5. **CI** : un workflow « tests » (ruff + pyright + pytest) sur chaque push et chaque pull request ; le déploiement
   ne part que si les tests passent. Travail sur des branches, fusion dans `main` par pull request. La CI échoue
   aussi si un identifiant Steam réel ou un pseudo de joueur réapparaît dans `src/` ou `tests/` (liste tenue
   hors du dépôt, dans un secret GitHub créé par Luc, pour ne pas les y réécrire ; la démarche est notée au
   moment de la phase B).
6. **Types** (retenu le 2026-11-16, voir § 4) : annotations complétées et vérifiées par pyright sur `store`,
   `account` et `worker` d'abord ; les autres modules suivent au fil des phases, à mesure qu'on les touche.
7. **Migrations avec Flyway** (décidé le 2026-11-16, « DB first ») :
   - `migrations/V1__schema_initial.sql` reprend exactement le schéma actuel (`SCHEMA` de `store.py`) ; la base de
     production existante est marquée à la version 1 sans rien réexécuter (`baselineOnMigrate`, `baselineVersion=1`).
   - **Schéma de production relevé le 2026-11-17** (`pg_dump --schema-only` fourni par Luc, Postgres 18.7) :
     `accounts`, `matches`, `match_players` et leurs index sont identiques à `SCHEMA` de `store.py` (y compris
     `accounts.sync_started`). Seul écart : une table **`games`** (`user_id`, `replay`, `status`, `replay_key`,
     `result`, `error`, `wall_s`, `worker`, `attempts`, `created_at`, `updated_at` ; clé `(user_id, replay)`, index
     `games_status`), reste d'une ancienne version (commit `d47dcb7`) que le code n'utilise plus. V1 la reprend
     telle quelle pour que la base vide et la production soient identiques. **Décidé le 2026-11-17 : elle est
     supprimée** par une migration `V2__supprimer_games.sql` (`DROP TABLE games`), puisqu'aucun code ne l'utilise
     (vérifié par `grep` dans `src/`). Contenu relevé en production le 2026-11-17 : 3 lignes, 1 joueur, toutes
     `ok`, créées le 2026-11-15 entre 20:19 et 20:20 UTC (essais du premier worker) : rien à conserver.
   - Le serveur et le worker n'exécutent plus aucun `CREATE`/`ALTER` : ils vérifient seulement au démarrage que la
     base est à la version attendue, et s'arrêtent avec un message clair sinon.
   - En local : un service Flyway (image officielle `flyway/flyway`, version à vérifier et à noter dans le journal)
     dans `docker-compose.dev.yml`, lancé avant le serveur et le worker. En CI : `flyway migrate` sur une base vide,
     puis les tests.
   - En production : Flyway lancé avant chaque déploiement du serveur et du worker. **Décidé le 2026-11-17 :
     Flyway dans l'image du serveur**, lancé au démarrage du conteneur avant le serveur (la « pre-deployment
     command » de Coolify tourne dans l'ancien conteneur) ; les workers attendent la bonne version. Décrit dans
     `docs/REGLAGES_COOLIFY.md`.
8. **Pages de `reports/`** (copie dans `rlpi-data-lainox/reports/` : `index.html`, `fantome.html`,
   `meilleur_jeu.html`, `modeles.html`, `swipe/`, `archives/`) : versionner les pages écrites à la main (dans
   `web/legacy/` par exemple) ou les recenser pour la phase F ; seules les sorties générées restent hors Git.

**Sortie** : `uv sync && pytest` passe sur une machine neuve ; pyright ne signale aucune erreur sur `store`,
`account` et `worker` ; la CI bloque un déploiement si un test échoue ; `flyway migrate` crée sur une base vide un
schéma identique à celui de la production, et `flyway info` en production affiche la version 1 sans erreur.

---

### Phase C — Découpler le calcul de la configuration globale (M)

**Objectif** : pouvoir calculer le tableau de bord de n'importe quel joueur, dans le même processus, sans
sous-processus ni liens symboliques. C'est le préalable des phases D et E.

- Introduire un objet `DataContext` (dossier des données, source, dossier des modèles, références) passé en
  paramètre à `make_payload()` et à toutes les sections de `dashboard.py` (et à `synergy`, `styles`…), au lieu de
  `config.DATA`, `config.FEATURES`, `config.SOURCE` lus à l'import.
- Les fonctions mises en cache (`lru_cache` sur la date de modification) prennent le contexte dans leur clé.
- `players.py` : suppression des sous-processus `_inner` et de `link_reference()` ; les références SSL/RLCS sont
  lues directement depuis leur dossier.
- Source de données `theo` (défaut de `RLPI_SOURCE`, fichiers `*_theo.parquet`, `frames/theo/`) renommée en un
  nom neutre (`perso`, déjà utilisé par le kit partagé) ; plus aucun nom de joueur dans le code.
- `config.py` ne garde que les valeurs par défaut et le chargement de `.env`.

**Sortie** : l'instantané de la phase B est identique, octet pour octet ; `/moi` ne lance plus aucun
sous-processus.

---

### Phase D — Agrégats pré-calculés par le worker (L)

**Objectif** : l'API ne fait plus de calcul lourd ; elle combine des agrégats déjà prêts.

0. **Schéma de `matches`** (retenu le 2026-11-16, voir § 4), avant les agrégats qui filtrent par période :
   - `played_at` passe de `text` à `timestamptz` (migration SQL qui convertit les valeurs existantes ; les valeurs
     illisibles sont listées avant d'être mises à `NULL`) ; index adaptés aux filtres de période ;
   - `status` limité aux valeurs connues par une contrainte `CHECK` (`en_attente`, `en_cours`, `ok`, `partiel`,
     `rejetee`, `erreur`, `doublon`), après vérification qu'aucune ligne existante n'y échappe.
   - Pas d'intervention manuelle sur la base de production (décidé le 2026-11-16) : ce sont des **migrations
     Flyway** (`V2__…sql`, voir phase B) qui font elles-mêmes les vérifications, dans des blocs `DO $$ … $$`. Les
     valeurs de `played_at` illisibles sont écrites dans les journaux (`RAISE NOTICE`) avant d'être mises à
     `NULL` ; si un `status` inconnu existe, la migration s'arrête (`RAISE EXCEPTION`, transaction annulée) en
     listant les lignes fautives. Chaque migration est d'abord essayée
     en local sur une base remplie avec le jeu d'essai.
1. **Inventaire des sections** du contenu actuel (`refs`, `value`, `peers`, `passes`, `heat`, `perf`, `synergy`,
   `compo`, `tech`, `record`, `style`, `advice`, `progress`, meilleur jeu) en trois familles :
   - **additives par partie** (sommes, comptes, grilles des cartes de chaleur) : on stocke la contribution de
     chaque partie et on additionne les parties retenues par les filtres ;
   - **comparaisons à une référence fixe** (centiles SSL/RLCS) : les distributions de référence sont calculées
     **une fois** (à chaque mise à jour des modèles ou des références) et stockées sous forme de quantiles ;
   - **non additives** (style, synergie, progression, meilleur jeu) : calculées à la volée sur les lignes par
     partie (petites tables), ou par le worker par joueur après chaque nouvelle partie.
2. **Stockage — décidé le 2026-11-16 : Postgres.** Tables par partie et par joueur (colonnes typées pour les
   indicateurs, sommes et quantités plutôt que moyennes ; `jsonb` pour les grilles et détails), index sur
   (joueur, date). Raisons : volumes modestes (≈ 2,4 millions de lignes au plafond estimé du serveur), écriture
   naturelle partie par partie par le worker, une seule technologie à opérer et à sauvegarder.
   Écarté pour l'instant : Parquet dans Garage lu avec DuckDB (petits fichiers à regrouper, mécanisme de plus).
   DuckDB reste possible plus tard pour les analyses sur tous les joueurs (il lit les tables Postgres directement).
3. **Worker** : nouvelle étape après le traitement d'une partie : calcul et écriture des agrégats des 6 joueurs ;
   commande de reconstruction complète (`python -m rlpi.worker rebuild-aggregates`) pour les changements de calcul.
4. **Version des données** : un compteur par joueur incrémenté à chaque nouvelle partie, utilisé pour le cache HTTP
   de l'API (`ETag`).
5. **Découpage de `dashboard.py`** (1 014 lignes ; retenu le 2026-11-16, voir § 4) : un module par section du
   tableau de bord, fait en même temps que l'inventaire et le passage aux agrégats.

**Sortie** : pour Théo, LAinox et Rileq, le contenu calculé depuis les agrégats est identique à celui de la
phase C (tolérance d'arrondi documentée) ; temps de réponse < 300 ms pour toute combinaison de filtres. En local,
LAinox et Rileq n'ont que les quelques parties jouées avec Théo : la comparaison porte sur celles-là.

**Réalisée le 2026-11-17** (détails dans `docs/JOURNAL_REFONTE_WEB.md`). Écarts au plan : références gardées en
entier plutôt qu'en quantiles (centiles inchangés au bit près) ; migrations V3 (`played_at`), V4 (`status`), V5
(tables d'agrégats) ; rattrapage automatique des agrégats par les workers en plus de la commande
`rebuild-aggregates` ; `players.py` supprimé dès cette phase (plus utilisé). Contenu identique (0 écart à 10
chiffres significatifs) pour les 4 joueurs locaux ; 50 à 170 ms de calcul (≈ 270 ms pour 200 parties).

---

### Phase E — API FastAPI (M)

**Objectif** : remplacer `serve.py` par une API JSON, en gardant les anciennes pages pendant la transition.

Organisation proposée : `src/rlpi/web/` (`main.py`, `deps.py`, `routes/`, `schemas.py`, `settings.py`).

| Route | Rôle |
|---|---|
| `GET /health` | le processus répond |
| `GET /ready` | Postgres, Redis et Garage joignables |
| `GET /auth/steam` · `GET /auth/steam/retour` · `POST /auth/deconnexion` · `POST /auth/deconnexion-partout` | connexion Steam, sessions révocables (voir ci-dessous) |
| `GET /api/moi` | joueur connecté, nombre de parties, état de l'import |
| `POST /api/moi/actualiser` | chercher les nouvelles parties (limite 1 / 5 min, inchangée) |
| `GET /api/moi/evenements` | flux d'événements (SSE) : « nouveau match traité » (voir ci-dessous) |
| `GET /api/joueurs/{id}/profil` | pseudo, coéquipiers proposés, parties par jour (sélecteur de dates) |
| `GET /api/joueurs/{id}/tableau?du=&au=&avec=&sans=&ref=` | contenu du tableau de bord (schéma Pydantic) |
| `GET /api/joueurs/{id}/matchs/{match}` | détail d'un match (onglet « Ce match », déroulé, ralentis) |
| `GET /api/modeles` | contenu de la page « Les modèles » |
| `GET /api/swipe/deck` · `POST /api/swipe/jugements` | outil de jugement à l'aveugle (porté en Vue, décidé le 2026-11-16) |

- **Droits — décidé le 2026-11-16 : chacun ne voit que le sien, connecté.** Toute route `/api/joueurs/{id}/…`
  exige une session et renvoie 403 si `id` n'est pas le joueur connecté (une dépendance FastAPI commune, testée).
  Aucun tableau de bord public, y compris celui de Théo ; pas de partage entre coéquipiers pour l'instant.
- **Sessions révocables** (retenu le 2026-11-16, voir § 4) : table `sessions` (identifiant aléatoire dans le
  cookie, joueur, date de création, dernière utilisation, expiration) au lieu d'un cookie signé qui contient
  directement l'identifiant Steam. La déconnexion supprime la session ; « se déconnecter partout » supprime toutes
  celles du joueur ; changer `RLPI_SECRET` ne déconnecte plus personne par accident. Transition sans déconnexion :
  un ancien cookie signé encore valide est accepté une fois et remplacé par une session.
- **Nouveau match traité** (retenu le 2026-11-16, voir § 4) : une fois les agrégats d'un match à jour (phase D),
  le worker publie un message Redis sur le canal du joueur concerné. `GET /api/moi/evenements` relaie ces messages
  au navigateur du joueur connecté (Server-Sent Events, un message vide toutes les 30 s pour garder la connexion
  ouverte à travers le proxy de Coolify). Aucun calcul ni lecture en base à chaque message : seulement
  l'identifiant du match et le nouveau nombre de parties.
- Les schémas Pydantic décrivent tout le contenu renvoyé ; l'OpenAPI sert à générer les types TypeScript.
- L'ancienne route `/moi` reste servie par FastAPI pendant la phase F, en réutilisant le gabarit actuel
  (`/tableau_de_bord.html` ne fait plus que rediriger vers `/moi`) ; `serve.py`, `pagecache.py` et le fil de pré-calcul sont retirés.
- `uvicorn --workers 2` dans le conteneur, limite mémoire Coolify ajustée.

**Sortie** : l'interface actuelle fonctionne en lisant l'API ; tests d'API (pytest + `httpx`) dans la CI ;
`/docs` décrit toutes les routes.

**Réalisée le 2026-11-17** (détails dans `docs/JOURNAL_REFONTE_WEB.md`). Écarts au plan : coéquipier affiché par
le paramètre `j` de sa propre route ; `POST /api/swipe/deck` ajouté ; paquet swipe fabriqué par le worker, avec les
cartes SSL / RLCS d'un lot fixe déposé dans `/app/data/swipe/` (décidé par Luc le 2026-11-17) ; message de maintien
du flux toutes les 15 s (valeur de FastAPI) ; migration V6 (sessions, swipe). Contenu de l'API identique à
l'instantané ; 180 à 490 ms au premier calcul d'une combinaison dans Docker Desktop (cache ensuite : 10 ms).

---

### Phase F — Interface Vue 3 (L)

**Objectif** : remplacer le gabarit de 1 492 lignes par une application Vue 3 qui suit l'architecture Plateau.

**Décidé par Luc le 2026-11-17, au démarrage de la phase** (remplace ce qui suit quand c'est contraire) :
- **Onglets : les 5 du gabarit actuel** (commit « parcours revu »), pas les 4 de la spec Plateau : Ma forme,
  Matchs, Mon jeu, À travailler, Mon trio, plus la vue « Tous les indicateurs ». Adresses : `/ma-forme`,
  `/matchs/{match}`, `/mon-jeu`, `/a-travailler`, `/mon-trio`, `/indicateurs`.
- **Fantôme pro retiré du site** (page publique avec les données d'un seul joueur) ; le générateur `rlpi.ghost`
  reste en ligne de commande. Pour la même raison, le bloc « Le meilleur jeu » (fichiers `bestplay_*.js` générés
  hors ligne pour un joueur, page `meilleur_jeu.html`) n'est pas porté.
- **Revue des resets non portée** (fonctionnalité en pause) : elle reste une page générée par `rlpi.mechanics`.
- **Image du serveur en deux étapes dès la phase F** (avancé de la phase G) : Node compile `web/`, l'image Python
  copie `web/dist`. Chaque fusion de la phase F reste déployable.

- Dossier `web/` : Vite + Vue 3 + TypeScript + vue-router ; jetons et grammaire de
  `Design/rlpi-plateau/design/` importés tels quels (une seule copie, fin des jetons recopiés dans le gabarit).
- Polices servies comme fichiers statiques, mis en cache longtemps (fin du base64 dans chaque page).
- **Composants** issus de `Design/rlpi-plateau/spec/COMPONENTS.md` : bandeau de score, forme (pavés V/D), note
  décomposée, classement de la partie, moments clés, Top 3 / Flop 3, écarts de style, carte terrain, face-à-face,
  barres de catégorie, panneau Méthode…
- **Filtres** (joueur, période, avec/sans, référence) dans l'adresse, mais appliqués par `fetch` : pas de
  rechargement de page, état de chargement visible, résultat précédent gardé à l'écran pendant le calcul.
- **Adresses des onglets — décidé le 2026-11-16 : chemins** (`/ma-forme`, `/ce-match/{match}`, `/mon-jeu`,
  `/mon-trio`, `/indicateurs`), en mode historique de vue-router ; les filtres restent en paramètres
  (`?du=&au=&avec=`). Côté FastAPI, une règle de repli renvoie `index.html` pour tout chemin qui n'est ni `/api/…`
  ni un fichier statique, pour qu'un lien ou une actualisation de page fonctionne.
- **Textes de l'interface** (retenu le 2026-11-16, voir § 4) : messages et libellés rassemblés dans un seul module
  (`web/src/copy/`), tirés de `Design/rlpi-plateau/spec/COPY.md`, au lieu d'être dispersés dans les composants.
- Pages annexes : connexion / import en cours, « Les modèles », revue des resets.
- **Nouveau match traité** (retenu le 2026-11-16, voir § 4) : l'application écoute `/api/moi/evenements`. À chaque
  match traité, un message discret s'affiche (« Nouveau match ajouté ») et le tableau de bord recharge ses données
  par `fetch`, sans recharger la page ni perdre les filtres. La page d'attente du premier import passe d'elle-même
  au tableau de bord dès le premier match (fin du rechargement toutes les 30 s). Si le flux est coupé, le
  navigateur se reconnecte seul ; sans flux possible, l'application interroge `/api/moi` toutes les minutes.
- **Outil swipe — décidé le 2026-11-16 : porté en Vue.** Page de l'application (`/swipe`), réservée au joueur
  connecté, alimentée par `/api/swipe/deck` ; les jugements sont enregistrés par `POST /api/swipe/jugements` (en
  base, plus dans un fichier). La page écrite à la main dans `reports/` est retirée. Aucun fichier de jugements
  n'existe encore : rien à importer.
- **Mode local — supprimé (décidé le 2026-11-17, remplace « mis de côté » du 2026-11-16).** Pas de portage en
  Vue : `app.py` part en phase A, le gabarit actuel, les polices en base64 et `dashboard.build()` en phase H.
- Migration **onglet par onglet**, dans cet ordre : Ma forme → Ce match → Mon jeu → Mon trio → Tous les
  indicateurs → panneau Méthode. Les deux interfaces coexistent (ex. `/v2/`) jusqu'à la fin.
- Tests : vitest sur les composants qui calculent ou formatent (centiles, signes, dates), `vue-tsc` dans la CI.
- Accessibilité : rôles `tablist`, navigation clavier, contrastes vérifiés (déjà prévus dans la spec Plateau).

**Sortie** : les 4 onglets et les pages annexes en Vue ; temps d'affichage initial < 1 s, changement de filtre
< 500 ms ; l'ancien gabarit n'est plus servi ; un match traité par le worker apparaît dans le tableau de bord
ouvert sans action du joueur ; le swipe fonctionne en ligne.

**Réalisée le 2026-11-18** (détails dans `docs/JOURNAL_REFONTE_WEB.md`). Écarts au plan : 5 onglets (décision de
Luc), fantôme, meilleur jeu et revue des resets non portés, image en deux étapes faite ici ; l'interface est servie
à la racine (anciennes adresses et `/v2/…` redirigées), les pages statiques du volume ne le sont plus. Textes de
chaque onglet et du panneau Méthode identiques à l'ancien gabarit ; premier affichage 0,2 s (0,8 à 1 s au premier
calcul d'une combinaison par un processus), changement de filtre 370 à 430 ms, dans Docker Desktop.

---

### Phase G — Déploiement et exploitation (M)

**Objectif** : une production que l'on surveille et que l'on peut restaurer.

- ~~**Image du serveur en deux étapes**~~ : faite en phase F (Node compile `web/`, l'image Python copie `dist/`).
- **Sauvegardes** : `pg_dump` quotidien vers Garage ; politique de rétention ; essai de restauration documenté.
  **Pas de copie hors du serveur pour le moment** (décidé le 2026-11-16).
- **Surveillance** : **pas d'alerte pour le moment** (décidé le 2026-11-16). `/ready` est en place pour pouvoir en
  ajouter plus tard (ex. Uptime Kuma) ; la taille de la file Redis et les parties bloquées « en_cours » sont
  visibles dans les journaux.
- **Journaux structurés** (JSON) avec identifiant de requête et durée, côté API et worker.
- **Pas d'environnement de recette** (décidé le 2026-11-16) : un seul environnement, la production, déployée à
  chaque push sur `main`. Les garde-fous sont donc avant le push : CI obligatoire (tests, lint, types, phase B),
  essai complet en local avec `docker-compose.dev.yml`, et nouvelles interfaces publiées à côté des anciennes
  (ex. `/v2/`) tant qu'elles ne sont pas validées.
- Mettre à jour `docs/DEPLOIEMENT_COOLIFY.md` (nouvelles variables, `/ready`, sauvegardes) en y reportant
  `docs/REGLAGES_COOLIFY.md`.

**Sortie** : restauration de la base testée une fois (en local, depuis une sauvegarde de Garage) ; journaux
structurés lisibles dans Coolify pour l'API et le worker.

**Réalisée le 2026-11-18** (détails dans `docs/JOURNAL_REFONTE_WEB.md`). Image en deux étapes déjà faite en phase F.
Sauvegarde quotidienne par le worker (`rlpi.backup`, 14 jours + 6 mois), restauration testée en local dans une base
neuve (11 tables identiques) ; journaux JSON (API avec `request_id`, worker avec ligne « état ») vérifiés dans
`docker-compose.dev.yml`, à contrôler dans Coolify à la fusion.

---

### Phase H — Nettoyage (S)

- Retirer `serve.py`, `pagecache.py` (`players.py`, remplacé par les agrégats, est déjà supprimé en phase D), les pages HTML écrites dans des
  chaînes Python (`account.py` : connexion, import et bandeau, inutilisés depuis la phase F ; garder la page de
  connexion de développement). `serve.py`, `pagecache.py` et `routes/legacy.py` sont déjà partis (phases E et F).
- Retirer aussi `dashboard_template.html`, `fonts.py` et `dashboard.build()` : le mode local est supprimé
  (décidé le 2026-11-17) et l'interface Vue les remplace.
- Mettre à jour `README.md`, `CLAUDE.md` (stack réelle) et `docs/JOURNAL.md`.

**Sortie** : plus aucun code mort ; le README permet d'installer et de lancer l'ensemble en local en 10 minutes.

**Réalisée le 2026-11-18** (détails dans `docs/JOURNAL_REFONTE_WEB.md`). `serve.py`, `pagecache.py` et
`players.py` étaient déjà partis (phases D et E). Pages HTML d'`account.py` et page autonome de `models_page.py`
supprimées (échec de connexion Steam et connexion de développement affichés par la page de connexion Vue) ;
`python -m rlpi.dashboard` écrit le contenu en JSON.

---

### Phase I — Worker, après la refonte (M)

Retenu le 2026-11-16 (voir § 4), **à faire seulement une fois la refonte terminée** (après les phases H et G).

- **Tâches en échec définitif** (« lettre morte ») : une file consultable, avec la cause et le nombre d'essais,
  plutôt qu'un simple statut `erreur` ; possibilité de relancer une tâche à la main.
- **Mesures** : durée par étape, parties traitées par heure, taille de la file, écrites dans les journaux
  structurés de la phase G.
- **Téléchargements Garage en parallèle** (nombre limité) lors des reconstructions.

**Sortie** : une tâche en échec est visible avec sa cause et peut être relancée ; les mesures apparaissent dans les
journaux ; une reconstruction complète est nettement plus rapide (durée avant / après notée dans le journal).

**Réalisée le 2026-11-18** (détails dans `docs/JOURNAL_REFONTE_WEB.md`). Lettre morte en base (migration V7,
`dead_tasks`, commandes `dead` et `retry`) ; durées par étape et débit horaire dans les journaux ; téléchargements
Garage et reconstruction en parallèle. Reconstruction de 55 parties : 16,1 s → 9,1 s sans limite de CPU, mais
inchangée (6,9 → 6,8 s) sous la limite de 1,5 CPU des workers de production, où le calcul domine : là, le levier
est la répartition entre workers (`rebuild-aggregates` sans `--here`).

---

## 4. Autres améliorations repérées

Non indispensables à la refonte, à placer selon les priorités.

**Sécurité et comptes**
- ~~Sessions révocables~~ → **retenu le 2026-11-16, phase E.**
- ~~Politique de sécurité du contenu (CSP) stricte~~, ~~limitation de débit sur les routes d'authentification et
  d'API~~, ~~données personnelles (page « confidentialité », suppression d'un compte et de ses données, retrait
  d'un pseudo sur demande)~~ → **écartés pour le moment** (2026-11-16). La CSP reste facile à ajouter après la
  phase F (plus de scripts ni de styles en ligne).

**Base de données**
- ~~`matches.played_at` en `timestamptz`~~ et ~~contrainte `CHECK` sur `matches.status`~~ → **retenus le
  2026-11-16, phase D (étape 0).**

**Worker**
- ~~Lettre morte, mesures, téléchargements Garage en parallèle~~ → **retenus le 2026-11-16, mais après la
  refonte : phase I.**

**Code**
- ~~Types vérifiés par pyright~~ → **retenu, phase B.** ~~Découpage de `dashboard.py`~~ → **retenu, phase D.**
  ~~Textes de l'interface rassemblés (`COPY.md`)~~ → **retenu, phase F.** (2026-11-16)

**Produit**
- ~~Notification quand un nouveau match est traité, et tableau de bord mis à jour sans recharger la page~~ →
  **retenu, phases E (flux d'événements) et F (affichage).** Remplace la page d'attente qui se recharge toutes
  les 30 s et le rechargement manuel après « chercher de nouvelles parties ». (2026-11-16)
- ~~Liens partageables vers un match ou une période~~ → **écarté pour le moment** (2026-11-16) : cohérent avec
  « chacun ne voit que le sien ». Les filtres restent dans l'adresse (phase F), ce qui permettra de l'ajouter plus
  tard sans refonte.

---

## 5. Décisions à prendre

| Question | Options | Recommandation |
|---|---|---|
| ~~Stockage des agrégats~~ | ~~Postgres / Parquet + DuckDB dans Garage~~ | **Décidé : Postgres** (2026-11-16, voir phase D) |
| ~~Qui voit quel tableau de bord ?~~ | ~~Seulement le sien / public par défaut / partage sur demande~~ | **Décidé : seulement le sien, après connexion ; plus aucun tableau de bord public** (2026-11-16, voir phases A et E) |
| ~~Mode local (app tkinter, page autonome)~~ | ~~Garder / abandonner au profit du site~~ | **Décidé : supprimé** (2026-11-17, remplace « mis de côté » du 2026-11-16 ; voir phases A, F et H) |
| ~~Outil swipe en ligne~~ | ~~Le porter en Vue / le laisser hors ligne~~ | **Décidé : porté en Vue**, en ligne (2026-11-16, voir phases E et F) |
| ~~Joueurs écrits en dur~~ | ~~Variable d'environnement / suppression~~ | **Décidé : suppression totale**, `RLPI_PLAYER` et `RLPI_COMPARE` compris (2026-11-17, voir phases A et C) |
| ~~Environnement de recette~~ | ~~Oui / non~~ | **Décidé : non**, seulement la production déployée depuis `main` (2026-11-16, voir phase G) |
| ~~URL des onglets~~ | ~~Ancre (`#ma-forme`) / chemin (`/ma-forme`)~~ | **Décidé : chemin** (2026-11-16, voir phase F) |

---

## 6. Ordre et dépendances

```
A ──► B ──► C ──► D ──► E ──► F ──► H ──► G ──► I (worker)
```

- G est fait à la fin, après le nettoyage (décidé le 2026-11-16).
- A et B d'abord : ils sécurisent l'existant et posent le garde-fou (instantané du contenu) dont dépend tout le reste.
- C est le verrou technique : sans lui, ni les agrégats ni l'API ne sont propres.
- E peut démarrer sur le calcul de la phase C si D prend du retard (l'API serait juste plus lente au début).
- La production n'est jamais coupée : anciennes et nouvelles routes coexistent jusqu'à la phase H.
