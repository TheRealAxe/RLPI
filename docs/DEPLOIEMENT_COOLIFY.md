# Mode opératoire — RLPI sur le Coolify de Luc (ThinkCentre M920q)

Serveur : Lenovo M920q, i5-9400T (6 cœurs), 16 Go de RAM, NVMe 476 Go, Ubuntu 24.04, Coolify déjà installé
(`coolify.lainox.quest`).

Ce document couvre deux choses :

- **Partie A — le tableau de bord actuel** : déjà branché (journal du 2026-11-15). Rappel des réglages pour le
  refaire ou le vérifier.
- **Partie B — la version multi-joueurs** : base de données, file d'attente, stockage, workers de traitement.
  Les étapes B1 à B4 peuvent se faire dès maintenant. **L'étape B5 (workers) attend le code** : le pipeline traite
  encore les parties par lot (« un dataset ») et doit d'abord être découpé partie par partie.

Les noms de menus Coolify ci-dessous sont ceux de la v4 ; ils peuvent légèrement varier selon la version.
Aucun mot de passe ni jeton ne doit être écrit dans ce document ni dans Git : ils restent dans Coolify et dans les
secrets GitHub.

---

## 0. Vérifications préalables (Luc, en SSH)

```bash
df -h /                     # espace libre réel (lsblk ne montre que la taille du disque)
docker stats --no-stream    # ce qui tourne déjà et ce que ça consomme
free -h
```

À noter : l'espace libre (prévoir ~1 Mo par partie analysée hors replay brut, ~2,5 Mo avec) et la RAM déjà prise
par les autres services. Le budget prévu pour RLPI est d'environ **5 Go de RAM et 4 cœurs** au total.

**Relevé du 2026-11-15** : 424 Go libres sur 468 Go (≈ 170 000 parties avec replay brut, ≈ 400 000 sans).
13 Go de RAM disponibles ; les 21 conteneurs existants (Coolify, dulbib, lineage, pihole, caddy…) prennent ≈ 1,2 Go
et presque pas de CPU. Un seul conteneur a une limite de mémoire : les autres peuvent grossir sans plafond, d'où
l'importance de limiter ceux de RLPI.

⚠️ `coolify-db` et `coolify-redis` sont les bases **internes de Coolify** : ne jamais les utiliser pour RLPI.
Les étapes B1 et B2 créent des instances dédiées.

---

## Partie A — Tableau de bord actuel

Circuit : push sur `main` → GitHub Action `.github/workflows/deploy.yml` → image `ghcr.io/therealaxe/rlpi`
(`:latest` et `:sha-…`) → appel de l'API Coolify qui redéploie.

### A1. Accès du serveur au registre privé ghcr.io

Le package ghcr est privé : le serveur doit pouvoir le télécharger.

1. Théo crée sur GitHub un jeton *classic* avec la seule permission `read:packages`.
2. Luc, en SSH sur le serveur :
   ```bash
   docker login ghcr.io -u therealaxe
   ```
   (coller le jeton quand il est demandé).

### A2. Créer l'application

1. Coolify → *Projects* → projet `RLPI` (le créer si besoin) → environnement `production`.
2. *+ New Resource* → *Docker Image* → image `ghcr.io/therealaxe/rlpi:latest`.
3. Onglet *General* :
   - *Ports Exposes* : `3001`
   - *Domains* : le domaine choisi (ex. `https://rlpi.lainox.quest`) ; Coolify gère le certificat HTTPS.
4. Onglet *Environment Variables* :
   | Variable | Valeur |
   |---|---|
   | `RLPI_HOST` | `0.0.0.0` |
   | `PORT` | `3001` |
   | `RLPI_REPORTS` | `/app/data/reports` |
   | `RLPI_SINCE` | facultatif, `AAAA-MM-JJ` |
5. Onglet *Persistent Storage* → *+ Add* → *Volume* :
   - nom : `rlpi-data`, chemin de destination : `/app/data`.
6. Onglet *Healthcheck* : laisser celui du Dockerfile (`/health`) ou indiquer chemin `/health`, port `3001`.
7. *Deploy*.

### A3. Charger les données dans le volume

Les données ne sont pas dans l'image (≈ 294 Mo lus par le tableau de bord ; archive envoyée à part,
ex. `rlpi-data-lainox.zip`).

```bash
# sur le serveur, après avoir copié l'archive dans /tmp
docker volume ls | grep rlpi-data           # nom exact du volume (Coolify le préfixe)
docker run --rm -v <nom_du_volume>:/data -v /tmp:/src alpine \
  sh -c "apk add --no-cache unzip && unzip -o /src/rlpi-data-lainox.zip -d /data && chown -R 1000:1000 /data"
```

Vérifier l'UID de l'utilisateur `app` de l'image avant le `chown` :
`docker run --rm ghcr.io/therealaxe/rlpi:latest id -u`.

Puis redémarrer l'application dans Coolify et ouvrir `https://<domaine>/health` → doit répondre `ok`.

### A4. Déploiement automatique depuis GitHub

1. Coolify → *Keys & Tokens* → *API tokens* → créer un jeton avec la seule permission **deploy**.
2. Récupérer l'UUID de l'application (dans l'adresse de sa page Coolify).
3. Dans le repo GitHub → *Settings* → *Secrets and variables* → *Actions* :
   `COOLIFY_TOKEN` et `COOLIFY_APP_UUID`.
4. Test : *Actions* → *Build & deploy* → *Run workflow*. L'application doit redémarrer dans Coolify.

---

## Partie B — Version multi-joueurs

Schéma :

```
Replay ─► Stockage (Garage) ─► File (Redis) ─► Workers (×3) ─► Postgres ─► Application web
                                              parse → frames → features → modèles → agrégation joueur
```

Tous les services sont dans le même projet Coolify `RLPI` : ils se joignent par leur nom interne sur le réseau
Docker de Coolify, sans exposer de port sur Internet (sauf l'application web et, si besoin, l'envoi de replays).

### B1. Postgres

1. *+ New Resource* → *Databases* → *PostgreSQL* (version 16 ou 17).
2. Nom : `rlpi-db`. Laisser Coolify générer le mot de passe.
3. **Ne pas cocher** *Make it publicly available*.
4. Onglet *Resource Limits* : mémoire `1g`.
5. *Start*. Noter l'URL de connexion interne (*Postgres URL (internal)*) : elle servira de variable
   `DATABASE_URL` aux workers et à l'application.

### B2. Redis (file d'attente)

1. *+ New Resource* → *Databases* → *Redis*. Nom : `rlpi-queue`. Non public.
2. *Resource Limits* : mémoire `256m`.
3. Noter l'URL interne → variable `REDIS_URL`.

### B3. Stockage S3 : Garage (stockage des replays et des résultats par partie)

Installé le 2026-11-15 : service Coolify `rlpi-storage`, image `dxflrs/garage:v2.3.0` (compatible S3, sans console
web : tout se fait en ligne de commande dans le conteneur).

1. **Réduire l'exposition** : Coolify a publié trois adresses `*.sslip.io` (S3 API, Web, Admin). Retirer l'URL
   **Admin** et l'URL **Web** (inutiles). Garder l'URL S3 seulement si un envoi de replays depuis l'extérieur est
   prévu ; sinon la retirer aussi, les workers passent par le réseau interne.
2. **Réseau** : *Network attachment* → choisir l'option qui rattache le service au réseau partagé de Coolify, pour
   que les workers (autres ressources) le joignent par son nom de conteneur.
3. **Initialiser Garage** (une seule fois), en SSH :
   ```bash
   G=$(docker ps --format '{{.Names}}' | grep -i garage | head -1)
   docker exec $G /garage status                       # repérer l'ID du nœud ; « NO ROLE ASSIGNED » = à configurer
   docker exec $G /garage layout assign -z maison -c 100G <id_du_noeud>
   docker exec $G /garage layout apply --version 1
   docker exec $G /garage bucket create rlpi
   docker exec $G /garage key create rlpi-app          # affiche Key ID et Secret : à garder hors de Git
   docker exec $G /garage bucket allow --read --write rlpi --key rlpi-app
   ```
   Si `garage status` montre déjà un rôle, passer directement à `bucket create`.
4. Variables pour les workers et l'application : `S3_ENDPOINT=http://<nom_du_conteneur_garage>:3900`,
   `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET=rlpi`, `S3_REGION=garage`. Côté code : adressage en mode
   « path-style » (pas de sous-domaine par bucket).

Organisation prévue dans le bucket :

```
rlpi/
  users/<id_utilisateur>/replays/<replay>.replay        (facultatif, ~1,6 Mo)
  users/<id_utilisateur>/frames/<replay>.parquet         (~0,7 Mo)
  users/<id_utilisateur>/features/<replay>/...           (~0,2 Mo)
```

Alternative plus simple si on ne veut pas de stockage S3 au début : un volume Docker partagé monté sur `/app/data`
dans les workers et l'application (comme en partie A). Le stockage S3 devient utile si les workers partent un jour ailleurs
(Cloud Run, autre serveur), car le code n'aura pas à changer.

### B4. Sauvegardes (avant d'accueillir le premier joueur)

Un seul disque, sans redondance : sans sauvegarde externe, une panne du NVMe efface tout.

1. Créer un bucket externe (Cloudflare R2 ou Backblaze B2) et une clé d'accès limitée à ce bucket.
2. Coolify → *S3 Storages* → *+ Add* → renseigner endpoint, bucket, clés → *Validate*.
3. `rlpi-db` → onglet *Backups* → *+ Add* → fréquence `0 4 * * *` (tous les jours à 4 h), stockage S3 ci-dessus,
   conserver 14 sauvegardes.
4. Garage / volume de données : copie nocturne vers le même bucket externe, par exemple avec `rclone` en tâche
   planifiée sur le serveur :
   ```bash
   # crontab -e (Luc) — features et frames seulement ; les replays bruts peuvent se re-télécharger
   30 4 * * * rclone sync garage:rlpi/users r2:rlpi-backup/users --exclude "*/replays/**" --log-file /var/log/rlpi-backup.log
   ```
5. **Tester une restauration** une fois (Postgres + quelques fichiers) avant d'annoncer le service.

### B5. Workers de traitement

Code prêt (2026-11-15) : `src/rlpi/worker.py`, image `Dockerfile.worker`, construite par la GitHub Action sous
`ghcr.io/therealaxe/rlpi-worker`. Le worker prend une tâche dans Redis, télécharge le replay dans Garage, lance
`rlpi.game run`, renvoie le dossier de la partie dans `users/<joueur>/games/<replay>/` et note le statut dans la
table Postgres `games` (créée automatiquement). Une partie interrompue est remise en file au redémarrage ; une
partie en erreur est retentée 3 fois.

**1. Modèles** : rien à faire sur le serveur. Les 6 fichiers nécessaires sont versionnés dans `models/` et copiés
dans l'image par la GitHub Action (voir `models/README.md` pour les mettre à jour après un réentraînement).

**2. Créer le worker dans Coolify** (après le premier push : l'image doit exister sur ghcr.io)

1. Projet `RLPI` → *+ New Resource* → *Docker Image* → `ghcr.io/therealaxe/rlpi-worker:latest`.
   Nom : `rlpi-worker-1`.
2. **Pas de domaine, pas de port exposé** (le worker n'écoute que la file). S'il y a un champ *Ports Exposes*
   obligatoire, le laisser vide ou mettre `80` sans domaine.
3. *Environment Variables* :
   | Variable | Valeur |
   |---|---|
   | `REDIS_URL` | URL interne de `rlpi-queue` |
   | `DATABASE_URL` | URL interne de `rlpi-db` |
   | `S3_ENDPOINT` | `http://<nom du conteneur garage>:3900` (ex. `http://garage-fj4rezthgm9pyk3rggqpjsw6:3900`) |
   | `S3_ACCESS_KEY`, `S3_SECRET_KEY` | clé Garage `rlpi-app` |
   | `S3_BUCKET` | `rlpi` |
   | `S3_REGION` | `garage` |
   | `BALLCHASING_TOKEN` | facultatif : clé API ballchasing, pour mettre en file des parties depuis ballchasing (B6) |
4. *Resource Limits* : mémoire **`1g`**, CPU **`1.5`** (mesuré : 410 Mo au pic sur la plus longue partie).
   Indispensable : sans limite, un import de 200 parties peut saturer la machine et les autres services de Luc.
5. Réseau : le worker doit joindre `rlpi-queue`, `rlpi-db` et Garage. Ils sont dans le même projet ; si Garage
   reste sur « stack network only », le rattacher au réseau partagé de Coolify (étape B3).
6. *Deploy*, puis dans *Logs* : `worker rlpi-worker-… prêt`.
7. Vérification complète, dans le *Terminal* du conteneur du worker :
   ```bash
   python -m rlpi.worker check
   ```
   Les quatre lignes doivent être « OK » : modèles, Redis, Postgres, stockage.
8. Déploiement automatique : ajouter dans GitHub le secret `COOLIFY_WORKER_UUIDS` = UUID du worker (plusieurs
   séparés par des virgules).
9. Plus tard : dupliquer en `rlpi-worker-2` et `rlpi-worker-3` (même configuration).

Budget total visé :

| Service | RAM | CPU |
|---|---|---|
| Postgres | 1 Go | — |
| Redis | 0,25 Go | — |
| Garage | 0,5 Go | — |
| Application web | 0,5 Go | — |
| 3 workers | 3 Go | 4,5 cœurs max |
| **Total** | **≈ 5 Go** | laisse ≥ 1,5 cœur au système et aux autres services |

C'est le CPU, pas la RAM, qui limite le nombre de workers.

### B6. Premier test de charge

Sans accès SSH, le plus simple est de passer par ballchasing (variable `BALLCHASING_TOKEN` du worker) :

1. Envoyer 3 parties 3v3 classées récentes sur ballchasing.com avec le compte de la clé API (bouton *Upload*,
   fichiers du dossier `Documents/My Games/Rocket League/TAGame/Demos`). Relevé du 2026-11-15 : l'auto-upload
   n'a tourné qu'en essai (`--dry-run`), le compte ne contient que des parties de 2019-2020.
2. Dans le *Terminal* du conteneur du worker :
   ```bash
   python -m rlpi.worker enqueue --user theo --ballchasing 3
   ```
   (les 3 parties classées 3v3 les plus récemment envoyées ; ou `--ballchasing-id <id> <id>` avec les
   identifiants visibles dans l'adresse des replays sur ballchasing.com).
3. Suivre les *Logs* du worker (`début …`, `fin … : ok en … s`), puis :
   ```bash
   python -m rlpi.worker status
   ```
4. Noter dans `docs/JOURNAL.md` : temps par partie, pic de RAM du worker (`docker stats`), température
   (`sensors`, paquet `lm-sensors`).
5. En déduire le temps d'import d'un nouveau joueur (ex. 50 parties ÷ 3 workers × temps par partie) et ajuster
   le nombre de workers et leurs limites.

Avec un accès SSH, on peut aussi copier des fichiers : `docker cp <dossier> <conteneur_du_worker>:/tmp/replays`
puis `python -m rlpi.worker enqueue --user theo /tmp/replays/*.replay`.

### B7. Surveillance au quotidien

- Coolify → *Notifications* : activer les alertes (Discord ou e-mail) pour échec de déploiement, conteneur arrêté
  et échec de sauvegarde.
- Espace disque : alerte si `/` dépasse 80 % (Coolify affiche l'usage disque du serveur dans *Servers*).
- Une fois par mois : vérifier qu'une sauvegarde récente existe dans le bucket externe.

---

## Récapitulatif des variables

| Variable | Utilisée par | Origine |
|---|---|---|
| `RLPI_HOST`, `PORT`, `RLPI_REPORTS`, `RLPI_SINCE` | application web | partie A |
| `DATABASE_URL` | application web, workers | B1 (URL interne Postgres) |
| `REDIS_URL` | application web, workers | B2 (URL interne Redis) |
| `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET` | application web, workers | B3 (clé Garage `rlpi-app`) |
| `COOLIFY_TOKEN`, `COOLIFY_APP_UUID` | GitHub Action | A4 (secrets GitHub) |
