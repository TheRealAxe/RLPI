# Mode opératoire — RLPI sur le Coolify de Luc (ThinkCentre M920q)

Serveur : Lenovo M920q, i5-9400T (6 cœurs), 16 Go de RAM, NVMe 476 Go, Ubuntu 24.04, Coolify déjà installé
(`coolify.lainox.quest`). Site : `https://rlpi.lainox.quest`.

Ce document décrit l'installation **telle qu'elle est après la refonte web** (phases A à I de
`docs/PLAN_REFONTE_WEB.md`, mise à jour en phases G et I le 2026-11-18). Les actions ponctuelles à faire au moment de
chaque fusion de la refonte (sauvegardes avant migration, variables à retirer…) sont dans
`docs/REGLAGES_COOLIFY.md` ; ce qui y reste valable en permanence est repris ici.

Les noms de menus Coolify sont ceux de la v4 ; ils peuvent légèrement varier selon la version. Aucun mot de passe
ni jeton ne doit être écrit dans ce document ni dans Git : ils restent dans Coolify et dans les secrets GitHub.

---

## 0. Vérifications préalables (Luc, en SSH)

```bash
df -h /                     # espace libre réel (lsblk ne montre que la taille du disque)
docker stats --no-stream    # ce qui tourne déjà et ce que ça consomme
free -h
```

Prévoir ~1 Mo par partie analysée hors replay brut, ~2,5 Mo avec. Budget de RLPI : environ **5 Go de RAM et
4 cœurs** au total.

**Relevé du 2026-11-15** : 424 Go libres sur 468 Go (≈ 170 000 parties avec replay brut, ≈ 400 000 sans).
13 Go de RAM disponibles ; les 21 conteneurs existants (Coolify, dulbib, lineage, pihole, caddy…) prennent ≈ 1,2 Go.
Un seul a une limite de mémoire : d'où l'importance de limiter ceux de RLPI.

⚠️ `coolify-db` et `coolify-redis` sont les bases **internes de Coolify** : ne jamais les utiliser pour RLPI.

---

## 1. Vue d'ensemble

Le worker calcule, l'API sert, le navigateur affiche.

```
Navigateur ──► Application web (image ghcr.io/therealaxe/rlpi : Flyway puis FastAPI + interface Vue)
                 │  lit les agrégats, ouvre les sessions, met des tâches en file
                 ▼
     Postgres (rlpi-db)   Redis (rlpi-queue)   Garage (rlpi-storage, bucket rlpi)
                 ▲                │                  ▲
                 └──── Workers (image ghcr.io/therealaxe/rlpi-worker, ×1 à 3) ─┘
                       file Redis → replay (ballchasing / Garage) → analyse → games/<partie>/ dans Garage
                       → agrégats par partie dans Postgres ; recherche des parties ; sauvegarde quotidienne
```

Tous les services sont dans le projet Coolify `RLPI` et se joignent par leur nom interne sur le réseau Docker de
Coolify ; seule l'application web est exposée sur Internet.

| Service | Image | RAM (limite) | CPU |
|---|---|---|---|
| Postgres `rlpi-db` | Postgres 18 (Coolify) | 1 Go | — |
| Redis `rlpi-queue` | Redis (Coolify) | 256 Mo | — |
| Garage `rlpi-storage` | `dxflrs/garage:v2.3.0` | 512 Mo | — |
| Application web | `ghcr.io/therealaxe/rlpi` | **768 Mo** (2 processus uvicorn + Flyway au démarrage) | — |
| Workers ×3 | `ghcr.io/therealaxe/rlpi-worker` | 1 Go chacun | 1,5 chacun |
| **Total** | | **≈ 5 Go** | laisse ≥ 1,5 cœur au système |

C'est le CPU, pas la RAM, qui limite le nombre de workers.

---

## 2. Déploiement

Circuit : push sur `main` → GitHub Actions : workflow **Tests** (ruff, pyright, pytest avec Postgres, Flyway sur
base vide, vue-tsc, vitest, construction de l'interface) → s'il passe, **Build & deploy** (`deploy.yml`) construit
les deux images, les publie sur ghcr.io (`:latest` et `:sha-…`) et demande à Coolify de redéployer l'application
web et les workers. Un seul environnement : la production (pas de recette, décidé le 2026-11-16).

### 2.1 Accès du serveur au registre privé ghcr.io

1. Théo crée sur GitHub un jeton *classic* avec la seule permission `read:packages`.
2. Luc, en SSH : `docker login ghcr.io -u therealaxe` (coller le jeton).

### 2.2 Secrets et règles GitHub

*Settings* → *Secrets and variables* → *Actions* :

| Secret | Rôle |
|---|---|
| `COOLIFY_TOKEN` | jeton API Coolify avec la seule permission **deploy** (*Keys & Tokens* → *API tokens*) |
| `COOLIFY_APP_UUID` | UUID de l'application web (dans l'adresse de sa page Coolify) |
| `COOLIFY_WORKER_UUIDS` | UUID des workers, séparés par des virgules |
| `RLPI_NOMS_INTERDITS` | identifiants Steam et pseudos réels, un par ligne : la CI échoue s'ils apparaissent dans `src/` ou `tests/` (sans ce secret, le workflow « Tests » échoue exprès) |

*Settings* → *Branches* : protection de `main` (« Require a pull request before merging », « Require status checks
to pass » avec le contrôle `tests`).

Test manuel : *Actions* → *Build & deploy* → *Run workflow*.

### 2.3 Migrations de la base

Le schéma est défini par les fichiers SQL de `migrations/` (Flyway, « DB first »). Le conteneur de l'application
web lance `python -m rlpi.migrate` **avant** le serveur : si une migration échoue, il ne démarre pas et Coolify garde
l'ancienne version en service. Les workers ne migrent pas : au démarrage, ils attendent jusqu'à 5 minutes
(`RLPI_SCHEMA_WAIT`) que la base soit à la version attendue.

- Ne **rien** mettre dans « Pre-deployment command » de Coolify (elle tourne dans l'ancien conteneur).
- État : `docker exec <conteneur web> python -m rlpi.migrate info`.
- Avant une fusion qui ajoute une migration : la sauvegarde automatique de la nuit suffit en général ; pour être
  tranquille, en lancer une juste avant (`docker exec <conteneur worker> python -m rlpi.backup run`, § 5).

---

## 3. Ressources

### 3.1 Postgres

1. *+ New Resource* → *Databases* → *PostgreSQL* **18** (la production est en 18.7). Nom : `rlpi-db`.
2. **Ne pas cocher** *Make it publicly available*. *Resource Limits* : mémoire `1g`.
3. Copier l'URL interne (*Postgres URL (internal)*, icône de copie) : variable `DATABASE_URL` de l'application et
   des workers.

### 3.2 Redis (file d'attente et événements)

1. *+ New Resource* → *Databases* → *Redis*. Nom : `rlpi-queue`. Non public. Mémoire `256m`.
2. URL interne → variable `REDIS_URL`.

### 3.3 Garage (stockage S3)

Service Coolify `rlpi-storage`, image `dxflrs/garage:v2.3.0` (installé le 2026-11-15 ; sans console web).

1. **Exposition** : retirer les URL publiques *Admin*, *Web* et *S3* (les services passent par le réseau interne).
2. **Réseau** : rattacher le service au réseau partagé de Coolify, pour que l'application et les workers le joignent
   par son nom de conteneur.
3. **Initialisation** (une seule fois), en SSH :
   ```bash
   G=$(docker ps --format '{{.Names}}' | grep -i garage | head -1)
   docker exec $G /garage status                       # « NO ROLE ASSIGNED » = à configurer
   docker exec $G /garage layout assign -z maison -c 100G <id_du_noeud>
   docker exec $G /garage layout apply --version 1
   docker exec $G /garage bucket create rlpi
   docker exec $G /garage key create rlpi-app          # Key ID et Secret : à garder hors de Git
   docker exec $G /garage bucket allow --read --write rlpi --key rlpi-app
   ```
4. Variables : `S3_ENDPOINT=http://<nom_du_conteneur_garage>:3900`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`,
   `S3_BUCKET=rlpi`, `S3_REGION=garage` (adressage « path-style »).

Contenu du bucket `rlpi` :

```
replays/<partie>.replay      replay brut (~1,6 Mo ; supprimé après traitement si RLPI_KEEP_REPLAYS=0)
games/<partie>/              résultat de l'analyse d'une partie (~1 Mo : images par image, variables, méta)
backups/rlpi-<date>.dump     sauvegardes quotidiennes de la base (§ 5)
```

### 3.4 Application web

1. *+ New Resource* → *Docker Image* → `ghcr.io/therealaxe/rlpi:latest`.
2. *General* : *Ports Exposes* `3001` ; *Domains* `https://rlpi.lainox.quest` (certificat géré par Coolify).
3. *Environment Variables* (le serveur refuse de démarrer s'il en manque une et nomme les absentes dans le journal) :
   | Variable | Valeur |
   |---|---|
   | `RLPI_PUBLIC_URL` | `https://rlpi.lainox.quest` (sans `/` final : sert aussi à vérifier l'origine des requêtes) |
   | `RLPI_SECRET` | longue chaîne aléatoire (`openssl rand -hex 32`) ; ne sert plus qu'à lire les cookies d'avant la phase E |
   | `DATABASE_URL`, `REDIS_URL` | URL internes de `rlpi-db` et `rlpi-queue` |
   | `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `S3_REGION` | § 3.3 |
   Facultatives : `RLPI_WEB_WORKERS` (processus uvicorn, défaut 2), `RLPI_DB_POOL_MAX` (connexions Postgres par
   processus, défaut 8). **Jamais** `RLPI_DEV_LOGIN` (connexion sans Steam ; refusée de toute façon en `https://`).
   Fixées dans l'image, à ne pas définir : `PORT`, `RLPI_WEB_DIST`, `RLPI_LOG_FORMAT`, `RLPI_SERVICE`,
   `FLYWAY_BIN`, `RLPI_MIGRATIONS`.
4. *Persistent Storage* : volume `rlpi-data` monté sur `/app/data`. Il contient ce que lit le calcul du tableau de
   bord et qui ne change qu'avec les modèles : `features/` et `frames/` (références RLCS / SSL), `models/`
   (rapports des modèles, `*.json`) et `swipe/reference_cards.json` (lot de cartes SSL / RLCS du swipe). Chargement
   initial :
   ```bash
   docker volume ls | grep rlpi-data           # nom exact du volume (Coolify le préfixe)
   docker run --rm -v <nom_du_volume>:/data -v /tmp:/src alpine \
     sh -c "apk add --no-cache unzip && unzip -o /src/rlpi-data-lainox.zip -d /data && chown -R 1000:1000 /data"
   ```
   (UID de l'utilisateur `app` : `docker run --rm ghcr.io/therealaxe/rlpi:latest id -u`.)
5. *Resource Limits* : mémoire **768 Mo** au moins.
6. *Healthcheck* : celui du Dockerfile (`/health`).
7. *Deploy*. Contrôles : `https://rlpi.lainox.quest/ready` → `{"postgres":"ok","redis":"ok","garage":"ok"}` ;
   `/docs` affiche la documentation de l'API ; `/` affiche la connexion Steam (navigation privée).

### 3.5 Workers

1. *+ New Resource* → *Docker Image* → `ghcr.io/therealaxe/rlpi-worker:latest`. Nom : `rlpi-worker-1`. **Pas de
   domaine ni de port.**
2. *Environment Variables* :
   | Variable | Valeur |
   |---|---|
   | `DATABASE_URL`, `REDIS_URL` | comme l'application web |
   | `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `S3_REGION` | comme l'application web |
   | `BALLCHASING_TOKEN` | clé API ballchasing du serveur (recherche et téléchargement des parties) |
   Facultatives (défauts corrects) : `RLPI_SYNC_MINUTES` (15), `RLPI_FIRST_SYNC` (50), `RLPI_BC_DOWNLOAD_INTERVAL`
   (18 s), `RLPI_KEEP_REPLAYS` (1), `RLPI_GAME_TIMEOUT` (900 s), `RLPI_SCHEMA_WAIT` (300 s), `RLPI_STATE_MINUTES`
   (5), `RLPI_S3_PARALLEL` (8), `RLPI_BACKUP_HOUR` (3, heure UTC), `RLPI_BACKUP_DAYS` (14), `RLPI_BACKUP_MONTHS` (6), `RLPI_WORKER_ID`
   (nom du conteneur).
3. *Resource Limits* : mémoire **`1g`**, CPU **`1.5`** (410 Mo mesurés au pic sur la plus longue partie).
4. *Deploy*, puis vérification complète :
   ```bash
   docker exec <conteneur worker> python -m rlpi.worker check   # 5 lignes OK : modèles, Redis, Postgres, stockage, ballchasing
   ```
5. Ajouter son UUID au secret GitHub `COOLIFY_WORKER_UUIDS`. Pour plus de débit : dupliquer en `rlpi-worker-2`,
   `rlpi-worker-3` (même configuration).

Les modèles (6 fichiers) sont dans l'image (`models/`, voir `models/README.md` pour les mettre à jour).

---

## 4. Comptes joueurs et recherche des parties

- Un joueur se connecte sur `https://rlpi.lainox.quest` avec Steam ; son SteamID est l'identifiant des replays.
  Session en base (table `sessions`, 30 jours), « se déconnecter partout » possible.
- À l'inscription, puis toutes les 15 minutes, les workers cherchent sur ballchasing les parties 3v3 où figure
  chaque inscrit, **quel que soit celui qui les a envoyées** (premier passage : 50 parties). Chaque partie n'est
  traitée qu'une fois et appartient à ses 6 joueurs (un même match envoyé deux fois → « doublon »).
- Le bouton « Chercher mes nouvelles parties » lance une recherche immédiate (une fois par 5 minutes). Le tableau de
  bord ouvert se met à jour seul à chaque partie traitée (« Nouveau match ajouté »).
- Chacun ne voit que son propre tableau de bord.

---

## 5. Sauvegardes

**Automatique** : chaque jour à partir de 3 h UTC (`RLPI_BACKUP_HOUR`), le premier worker libre fait un `pg_dump`
de la base et l'écrit dans Garage (`backups/rlpi-AAAAMMJJTHHMMSSZ.dump`, quelques Mo). Un seul par jour, tous workers
confondus ; en cas d'échec, nouvel essai une heure plus tard. Rétention : toutes les sauvegardes des 14 derniers
jours, plus la première de chacun des 6 derniers mois. Journal du worker : `sauvegarde écrite` (clé, taille,
durée) ou `sauvegarde : échec …` (niveau `error`).

⚠️ **Pas de copie hors du serveur pour le moment** (décidé le 2026-11-16) : Garage est sur le même disque que
Postgres. Une panne du NVMe perd la base et ses sauvegardes. Pour y remédier plus tard : copier `backups/` vers un
stockage externe (Cloudflare R2, Backblaze B2) avec `rclone` en tâche planifiée, ou activer les sauvegardes S3 de
Coolify sur `rlpi-db` (*Backups* → stockage externe).

Commandes (dans un worker) :

```bash
docker exec <conteneur worker> python -m rlpi.backup list     # sauvegardes présentes, avec leur taille
docker exec <conteneur worker> python -m rlpi.backup run      # sauvegarder maintenant (avant une opération risquée)
docker exec <conteneur worker> python -m rlpi.backup prune    # appliquer la rétention
```

### Restaurer

La restauration se fait **toujours dans une base vide** (la commande refuse une base qui contient des tables) ; on
bascule ensuite. La sauvegarde contient l'historique Flyway : la base restaurée est à la bonne version.

```bash
P=<conteneur postgres>; W=<conteneur worker>; U=<utilisateur postgres>; B=<base>   # B : nom de la base dans DATABASE_URL
# 1. Base neuve et restauration de la dernière sauvegarde (ou d'une clé donnée par « list »)
docker exec $P psql -U $U -d postgres -c "CREATE DATABASE rlpi_restauration"
docker exec $W sh -c 'python -m rlpi.backup restore latest --into "${DATABASE_URL%/*}/rlpi_restauration"'
# 2. Contrôle : mêmes ordres de grandeur que d'habitude
docker exec $P psql -U $U -d rlpi_restauration -c "SELECT (SELECT count(*) FROM accounts) comptes, (SELECT count(*) FROM matches) parties"
# 3. Bascule : arrêter l'application web et les workers dans Coolify (Stop), puis
docker exec $P psql -U $U -d postgres -c "ALTER DATABASE $B RENAME TO rlpi_avant_restauration" -c "ALTER DATABASE rlpi_restauration RENAME TO $B"
# 4. Redémarrer l'application web puis les workers ; quand tout va bien : DROP DATABASE rlpi_avant_restauration
```

(`${DATABASE_URL%/*}` = l'URL sans le nom de la base ; si `DATABASE_URL` se termine par des options `?…`, écrire
l'URL à la main.)

**Essai de restauration** fait le 2026-11-18 en local (`docker-compose.dev.yml`) : sauvegarde de 2,9 Mo en 0,6 s,
restaurée dans une base neuve, les 11 tables ont le même nombre de lignes que l'original. À refaire en production
une fois (étapes 1 et 2 seulement, puis `DROP DATABASE rlpi_restauration`).

Le contenu de Garage (`games/`, `replays/`) n'est pas sauvegardé à part : il se reconstruit en retraitant les
parties depuis ballchasing.

---

## 6. Journaux et surveillance

Les journaux de l'application web et des workers sont en **JSON, une ligne par événement** (onglet *Logs* de
Coolify) : `ts` (UTC), `level` (`info`, `warning`, `error`), `service` (`web`, `worker`), `msg`, puis des champs
propres à l'événement. Filtrer dans Coolify (ou `docker logs <conteneur> | grep '"error"'`).

- **Application web** : une ligne `requête` par appel (`method`, `path` sans paramètres, `status`, `ms`,
  `request_id`) ; jamais de cookie. `request_id` est aussi renvoyé dans l'en-tête `X-Request-ID` et ajouté aux
  autres lignes écrites pendant la requête : il permet de retrouver tout ce qui concerne un appel. Au démarrage :
  lignes Flyway (`"outil": "flyway"`), `Base de données en version N`, `Application startup complete.` (une par
  processus).
- **Workers** : `début de partie` / `fin de partie` (`match`, `statut`, `fichiers`, `erreur` et la durée de
  chaque étape : `t_replay` récupération du replay, `t_analyse` analyse avec le détail dans `etapes`, `t_envoi`
  envoi vers Garage, `t_agregats`), `agrégats écrits`, `lettre morte`, `sync …`, `sauvegarde écrite`, et toutes
  les 5 minutes une ligne **`état`** écrite par un seul worker : `file` (tâches en attente), `en_cours`,
  `bloquees` (parties « en_cours » depuis plus de 30 min), `erreurs_24h`, `parties_1h` (parties terminées dans
  l'heure), `duree_moy_s_1h`, `lettre_morte` (tâches abandonnées pas encore relancées). La ligne passe en
  `warning` s'il y a des parties bloquées ou des tâches en lettre morte.
- Commandes lancées à la main (`rlpi.worker status`, `rlpi.backup list`…) : sortie en texte lisible.

**Pas d'alerte pour le moment** (décidé le 2026-11-16). Pour en ajouter plus tard : une sonde (ex. Uptime Kuma)
sur `https://rlpi.lainox.quest/ready` (503 si Postgres, Redis ou Garage est injoignable) ; Coolify →
*Notifications* pour les échecs de déploiement et les conteneurs arrêtés.

À regarder de temps en temps : ligne `état` des workers (file qui ne descend pas, parties bloquées, lettre morte),
présence d'une `sauvegarde écrite` chaque nuit, espace disque (Coolify → *Servers*, viser moins de 80 %).

### Lettre morte

Une tâche abandonnée par les workers (partie encore en erreur après 3 essais, agrégats impossibles à calculer, tâche
illisible) est gardée dans la table `dead_tasks` avec sa cause, son nombre d'essais et le worker. Une partie
**rejetée** (replay illisible ou hors format, 2v2…) n'y va pas : c'est un résultat, pas une panne.

```bash
docker exec <worker> python -m rlpi.worker dead            # tâches en attente : numéro, date, type, partie, essais, cause
docker exec <worker> python -m rlpi.worker retry 12 13     # remettre en file (une partie repart avec 0 essai)
docker exec <worker> python -m rlpi.worker retry --all     # toutes, une fois la cause corrigée
docker exec <worker> python -m rlpi.worker dead --all      # historique, relancées comprises
```

---

## 7. Opérations courantes

```bash
docker exec <worker> python -m rlpi.worker status                  # parties par statut, dernières erreurs, joueurs inscrits, file
docker exec <worker> python -m rlpi.worker add-player Steam:7656…  # inscrire un joueur sans le site
docker exec <worker> python -m rlpi.worker sync [--player Steam:…] # chercher les nouvelles parties maintenant
docker exec <worker> python -m rlpi.worker enqueue --ballchasing-id <id> …
docker exec <worker> python -m rlpi.worker rebuild-aggregates      # agrégats manquants ou périmés remis en file (--all : tous)
docker exec <worker> python -m rlpi.worker rebuild-aggregates --all --here --parallel 3   # … ou calculés tout de suite ici
docker exec <worker> python -m rlpi.worker dead | retry …           # lettre morte (§ 6)
docker exec <web>    python -m rlpi.migrate info                   # état des migrations
```

- **Changement de calcul d'un indicateur par partie** : il suffit de déployer (le code augmente
  `aggregate.VERSION` ; au démarrage, un worker remet en file les parties concernées).
- **Lot de cartes SSL / RLCS du swipe** : fabriqué sur un poste qui a les replays bruts
  (`python -m rlpi.swipe pool --n 60` → `data/swipe/reference_cards.json`), déposé dans le volume
  (`/app/data/swipe/reference_cards.json`, comme le chargement initial du § 3.4).

---

## Récapitulatif des variables

| Variable | Utilisée par | Obligatoire | Origine / défaut |
|---|---|---|---|
| `DATABASE_URL` | web, workers | oui | URL interne de `rlpi-db` (§ 3.1) |
| `REDIS_URL` | web, workers | oui | URL interne de `rlpi-queue` (§ 3.2) |
| `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | web, workers | oui | Garage, clé `rlpi-app` (§ 3.3) |
| `S3_BUCKET`, `S3_REGION` | web, workers | non | `rlpi`, `garage` |
| `RLPI_PUBLIC_URL`, `RLPI_SECRET` | web | oui | § 3.4 |
| `RLPI_WEB_WORKERS`, `RLPI_DB_POOL_MAX` | web | non | 2, 8 |
| `BALLCHASING_TOKEN` | workers | oui | clé API ballchasing du serveur |
| `RLPI_SYNC_MINUTES`, `RLPI_FIRST_SYNC`, `RLPI_BC_DOWNLOAD_INTERVAL` | workers | non | 15, 50, 18 |
| `RLPI_KEEP_REPLAYS`, `RLPI_GAME_TIMEOUT`, `RLPI_SCHEMA_WAIT` | workers | non | 1, 900, 300 |
| `RLPI_STATE_MINUTES` | workers | non | 5 (ligne « état » du journal) |
| `RLPI_S3_PARALLEL` | workers | non | 8 (fichiers d'une partie téléchargés en même temps depuis Garage) |
| `RLPI_BACKUP_HOUR`, `RLPI_BACKUP_DAYS`, `RLPI_BACKUP_MONTHS` | workers | non | 3 (UTC, `off` : jamais), 14, 6 (§ 5) |
| `RLPI_LOG_FORMAT` | web, workers | non | `json`, fixé dans les images |
| `RLPI_DEV_LOGIN` | développement seulement | **jamais en production** | — |
| `COOLIFY_TOKEN`, `COOLIFY_APP_UUID`, `COOLIFY_WORKER_UUIDS`, `RLPI_NOMS_INTERDITS` | GitHub Actions | oui | secrets GitHub (§ 2.2) |

Variables qui n'existent plus (à retirer si elles traînent dans Coolify) : `RLPI_HOST`, `RLPI_REPORTS`,
`RLPI_SINCE`, `RLPI_PLAYER`, `RLPI_COMPARE`, `RLPI_SOURCE`, `RLPI_USERS_CACHE`, `RLPI_PAGES_CACHE`.
