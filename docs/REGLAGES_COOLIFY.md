# Réglages Coolify à faire à la main — refonte web

Tenu au fil des phases de `docs/PLAN_REFONTE_WEB.md`. C'est Luc qui les applique (accès Coolify et SSH).
Chaque réglage indique la phase, la ressource et le moment (avant ou après la fusion dans `main`).
Depuis la phase G, la description complète et à jour de l'installation est `docs/DEPLOIEMENT_COOLIFY.md` ; ce fichier
ne garde que les actions ponctuelles à faire au moment de chaque fusion.

## Phase A — Corrections immédiates

| Fait | Ressource | Réglage | Quand |
|---|---|---|---|
| ☐ | Application web (tableau de bord) | Supprimer les variables `RLPI_PLAYER` et `RLPI_COMPARE` si elles existent : le code ne les lit plus (aucun joueur n'est fixé, chacun voit son tableau de bord après connexion Steam). | Après la fusion (sans effet avant, mais inutiles) |
| ☐ | Application web | Supprimer `RLPI_SINCE` si elle existe : elle ne servait qu'au tableau de bord public, retiré. | Après la fusion |
| ☐ | Application web | Vérifier que `RLPI_DEV_LOGIN` **n'existe pas** (connexion sans Steam, développement seulement). Par sécurité, le serveur refuse de démarrer si elle vaut `1` alors que `RLPI_PUBLIC_URL` est en `https://`. | Avant la fusion |
| ☐ | Application web | Vérifier que `RLPI_PUBLIC_URL` vaut exactement `https://rlpi.lainox.quest` (sans `/` final) : elle sert maintenant aussi à vérifier l'origine du bouton « Chercher mes nouvelles parties » (sinon le bouton répond « Requête refusée »). | Avant la fusion |
| ☐ | Application web | Facultatif : `RLPI_DB_POOL_MAX` (défaut 8), nombre maximal de connexions Postgres ouvertes par le serveur. Rien à faire avec la valeur par défaut. | — |

Rien à changer pour les workers : ils gardent leurs variables. Les deux images installent maintenant
`psycopg-pool` (fait par la GitHub Action, rien à faire à la main).

## Phase B — Socle qualité

Réglages GitHub et Coolify. Les trois premiers sont à faire **avant la fusion** de la branche dans `main`.

| Fait | Ressource | Réglage | Quand |
|---|---|---|---|
| ☐ | GitHub (Settings > Secrets and variables > Actions) | Créer le secret **`RLPI_NOMS_INTERDITS`** : identifiants Steam (17 chiffres, sans « Steam: ») et pseudos réels des joueurs suivis (Théo, ses coéquipiers…), **un par ligne**. La CI échoue si l'un d'eux apparaît dans `src/` ou `tests/` (mot entier, majuscules respectées ; seuls les noms de fichiers sont affichés). **Sans ce secret, le workflow « Tests » échoue** (exprès, pour ne pas sauter le contrôle en silence). Éviter les pseudos qui sont aussi des mots courants du code (ils déclencheraient de fausses alertes). | Avant le prochain push si possible, sinon avant la fusion |
| ☐ | GitHub (Settings > Branches) | Règle de protection sur `main` : « Require a pull request before merging » et « Require status checks to pass » avec le contrôle **`tests`** (workflow « Tests »). La fusion se fait alors par pull request, après des tests verts. | Avant la fusion |
| ☐ | Postgres (SSH sur le serveur) | **Sauvegarde avant la première migration** : `docker exec <conteneur postgres> pg_dump -U <utilisateur> -Fc <base> > rlpi_avant_flyway.dump`. Au premier démarrage, Flyway marque la base en version 1 sans rien réexécuter, puis la migration 2 supprime la table inutilisée `games` (3 lignes d'essai). | Juste avant la fusion |
| ☐ | Application web | Mémoire : au démarrage, le conteneur lance Flyway (Java) avant le serveur, quelques secondes et environ 200 à 300 Mo. Si une limite mémoire inférieure à 512 Mo est fixée dans Coolify, la porter à 512 Mo au moins. L'image grossit d'environ 240 Mo (Java et Flyway). | Avant la fusion |
| ☐ | Application web | Ne **rien** mettre dans « Pre-deployment command » pour les migrations : Coolify l'exécute dans l'ancien conteneur, qui n'a pas les nouvelles migrations. Elles sont lancées par le nouveau conteneur lui-même (`python -m rlpi.migrate`, puis le serveur) ; si elles échouent, il ne démarre pas et l'ancienne version reste en service. | — |
| ☐ | Application web (journaux du déploiement) | Après la fusion, vérifier dans les journaux de l'application : `Successfully baselined schema with version: 1`, puis `now at version v2`, puis `Base de données en version 2`. État à tout moment : `docker exec <conteneur web> python -m rlpi.migrate info` (lignes `<< Flyway Baseline >>` en version 1 et `supprimer games` en version 2, état `Success`). | Après la fusion |
| ☐ | Postgres (facultatif) | Contrôle du schéma : `docker exec <conteneur postgres> pg_dump -U <utilisateur> -d <base> --schema-only --no-owner -T flyway_schema_history` doit être identique (hors commentaires) à celui d'une base vide migrée en local (`docker compose -f docker-compose.dev.yml run --rm flyway migrate` sur une base neuve). | Après la fusion |
| ☐ | Workers | Rien à régler. Au démarrage, un worker attend jusqu'à 5 minutes (`RLPI_SCHEMA_WAIT`, défaut 300 s) que le serveur ait passé les migrations, puis s'arrête avec un message clair si la base n'est toujours pas à jour (Coolify le relance). | — |

Variables nouvelles (facultatives, valeurs par défaut correctes) : `RLPI_SCHEMA_WAIT` (workers). Les variables
`FLYWAY_BIN` et `RLPI_MIGRATIONS` sont fixées dans l'image du serveur : ne pas les définir dans Coolify.

## Phase C — Calcul dans le processus du serveur

| Fait | Ressource | Réglage | Quand |
|---|---|---|---|
| ☐ | Volume `/app/data` de l'application web (SSH) | Renommer deux clés du rapport de l'indice de performance : `docker exec <conteneur web> sed -i 's/"theo_team_acc"/"perso_team_acc"/; s/"theo_n_matches"/"perso_n_matches"/' /app/data/models/perf_report.json`, puis vérifier avec `docker exec <conteneur web> grep -c perso_team_acc /app/data/models/perf_report.json` (doit afficher `1`). Si le fichier n'est pas modifiable par l'utilisateur `app`, passer par le volume comme en A3 de `DEPLOIEMENT_COOLIFY.md` (`docker run --rm -v <nom_du_volume>:/data alpine sed -i … /data/models/perf_report.json`). Sans ce changement, la carte « Validation » de l'indice affiche des valeurs vides. L'ancien code lit aussi les nouvelles clés : on peut le faire tout de suite. | **Avant la fusion** |
| ☐ | Application web | Supprimer `RLPI_SOURCE` si elle existe (le serveur ne la lit plus ; le dossier de chaque joueur est toujours « perso »). | Après la fusion |
| ☐ | Volume `/app/data` (facultatif) | Les fichiers `features/*_theo.*` et `frames/theo/` ne sont plus lus par le serveur (seules les références RLCS/SSL et `models/` le sont). Ils peuvent rester ; les supprimer libère de la place. | Après la fusion, quand on veut |
| ☐ | Application web (facultatif) | Le cache des joueurs (`/app/cache/players/`) garde des liens vers les références, créés par l'ancien code ; ils ne gênent pas et disparaissent à la prochaine partie de chaque joueur. Pour repartir propre : `docker exec <conteneur web> rm -rf /app/cache/players` (chaque joueur est reconstruit à sa prochaine visite, environ 10 à 15 s). | Après la fusion |

Rien à changer pour les workers.

## Phase D — Agrégats pré-calculés par le worker

Aucune variable nouvelle. Les migrations 3, 4 et 5 passent toutes seules au démarrage du nouveau conteneur web
(comme en phase B) ; les workers attendent la version 5, puis calculent eux-mêmes les agrégats des parties déjà
traitées (rattrapage automatique, rien à lancer à la main).

| Fait | Ressource | Réglage | Quand |
|---|---|---|---|
| ☐ | Postgres (SSH) | **Vérifier les statuts** : `docker exec <conteneur postgres> psql -U <utilisateur> -d <base> -c "SELECT status, count(*) FROM matches GROUP BY 1"`. Seuls `en_attente`, `en_cours`, `ok`, `partiel`, `rejetee`, `erreur`, `doublon` sont admis par la migration 4 ; sinon elle s'arrête (rien n'est modifié, l'ancienne version reste en service) en listant les parties fautives. Me les signaler le cas échéant. | **Avant la fusion** |
| ☐ | Postgres (SSH) | Sauvegarde avant les migrations, comme en phase B : `docker exec <conteneur postgres> pg_dump -U <utilisateur> -Fc <base> > rlpi_avant_phase_d.dump`. La migration 3 convertit `matches.played_at` (texte) en date ; une valeur illisible est mise à vide et écrite dans le journal du déploiement (`played_at illisible, mis à NULL : partie …`). | Juste avant la fusion |
| ☐ | Application web (journaux) | Après la fusion : `now at version v5`, `Base de données en version 5`, puis `référence du tableau de bord recalculée (…)` quelques secondes après le démarrage (références RLCS / SSL lues dans `/app/data`, comme avant). | Après la fusion |
| ☐ | Workers (journaux) | Après la fusion : `rattrapage : N partie(s) sans agrégats à jour mise(s) en file` (N = parties déjà traitées), puis une ligne `agrégats <partie> en x s` par partie (moins d'une seconde chacune, téléchargement compris). Pendant le rattrapage, le tableau de bord affiche « N partie(s) en préparation » ; un joueur dont aucune partie n'est encore prête voit la page d'import (elle se met à jour toute seule). | Après la fusion |
| ☐ | Workers (facultatif) | Si une partie reste « en préparation » : `docker exec <conteneur worker> python -m rlpi.worker rebuild-aggregates` (remet en file les parties sans agrégats à jour ; `--all` pour toutes, `--here` pour les calculer dans la commande en affichant les erreurs). | Si besoin |
| ☐ | Application web (facultatif) | Le cache des joueurs `/app/cache/players/` n'est plus utilisé (le serveur lit les agrégats dans Postgres) : `docker exec <conteneur web> rm -rf /app/cache/players` libère la place. `/app/cache/pages/` reste utilisé. | Après la fusion, quand on veut |
| ☐ | Application web (facultatif) | Mémoire : le serveur garde en mémoire les parties des 16 derniers joueurs consultés et la référence (quelques Mo chacun) ; plus de dossiers de joueurs sur le disque. Rien à changer si la limite est d'au moins 512 Mo (phase B). | — |

## Phase E — API FastAPI

Le serveur devient une API FastAPI (uvicorn, 2 processus). La migration 6 (sessions, swipe) passe toute seule au
démarrage du nouveau conteneur web ; les workers attendent la version 6. Personne n'est déconnecté : un ancien
cookie encore valide est remplacé par une session à la première visite.

| Fait | Ressource | Réglage | Quand |
|---|---|---|---|
| ☐ | Postgres (SSH) | Sauvegarde avant la migration 6, comme en phase B : `docker exec <conteneur postgres> pg_dump -U <utilisateur> -Fc <base> > rlpi_avant_phase_e.dump`. | Juste avant la fusion |
| ☐ | Application web | **Mémoire** : 2 processus uvicorn au lieu d'un seul (≈ 280 Mo en local après quelques tableaux de bord), plus Flyway au démarrage. Si une limite mémoire est fixée, la porter à **768 Mo** au moins. Pour économiser la mémoire : variable `RLPI_WEB_WORKERS=1` (un seul processus, comme avant). | Avant la fusion |
| ☐ | Application web | Vérifier que **toutes** ces variables existent : `RLPI_PUBLIC_URL`, `RLPI_SECRET`, `DATABASE_URL`, `REDIS_URL`, `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`. Le serveur refuse maintenant de démarrer s'il en manque une (avant, il servait seulement les pages statiques) ; le journal du déploiement nomme alors les variables manquantes, et Coolify garde l'ancienne version. `RLPI_SECRET` ne sert plus qu'à lire les anciens cookies : ne pas le changer avant quelques semaines. | Avant la fusion |
| ☐ | Application web (journaux) | Après la fusion : `now at version v6` puis `Base de données en version 6`, `Uvicorn running on http://0.0.0.0:3001`, deux lignes `Application startup complete.` Ensuite une ligne par requête (`GET /moi 200 12 ms`), comme avant. | Après la fusion |
| ☐ | Application web | Contrôles après la fusion : `https://rlpi.lainox.quest/ready` doit répondre `{"postgres":"ok","redis":"ok","garage":"ok"}` ; `https://rlpi.lainox.quest/docs` affiche la documentation de l'API ; `/moi` affiche le tableau de bord comme avant (les filtres de période et de coéquipiers rechargent la page, comme avant). | Après la fusion |
| ☐ | Application web | Flux « nouveau match » à travers le proxy : connecté sur `/moi`, ouvrir la console du navigateur (F12) et taper `new EventSource('/api/moi/evenements').addEventListener('connecte', e => console.log('flux ouvert', e.data))`. « flux ouvert » doit s'afficher en une seconde ; l'onglet Réseau montre ensuite la requête `evenements` toujours en cours, avec un message `ping` toutes les 15 s. Si rien n'arrive, le proxy de Coolify met la réponse en mémoire : me le signaler (rien de cassé en attendant). | Après la fusion |
| ☐ | Application web | Supprimer les variables devenues inutiles si elles existent : `RLPI_HOST`, `RLPI_USERS_CACHE`, `RLPI_PAGES_CACHE` (le cache de pages sur disque n'existe plus). | Après la fusion |
| ☐ | Application web (facultatif) | Le stockage persistant monté sur `/app/cache` (s'il existe) n'est plus utilisé : il peut être retiré dans Coolify (onglet « Persistent Storage »), puis le volume supprimé. | Après la fusion, quand on veut |
| ☐ | Poste de Théo puis volume `/app/data` | **Lot de cartes SSL / RLCS du swipe** (sur un poste qui a les replays bruts RLCS et SSL, ceux cités dans `data/frames/*/…meta.json`) : `.venv/Scripts/python -m rlpi.swipe pool --n 60` → `data/swipe/reference_cards.json` (quelques Mo). Le déposer dans le volume : `docker cp reference_cards.json <conteneur web>:/app/data/swipe/reference_cards.json` (créer le dossier avant : `docker exec <conteneur web> mkdir -p /app/data/swipe`), ou par le volume comme en A3 de `DEPLOIEMENT_COOLIFY.md` si le dossier n'est pas modifiable. Sans ce fichier, le swipe fonctionne avec seulement les cartes des parties du joueur. | Après la fusion, quand on veut |
| ☐ | Workers | Rien à régler : ils savent fabriquer les paquets du swipe (tâche `swipe`) et annoncer les nouvelles parties. Journaux : `swipe <n> : <k> cartes en <s> s` quand un joueur demande un paquet. | — |

Variables nouvelles (facultatives) : `RLPI_WEB_WORKERS` (application web, défaut 2). `PORT` reste à 3001.

## Phase F — Interface Vue 3

L'image du serveur compile maintenant l'interface (étape Node dans le `Dockerfile`, faite par la GitHub Action :
rien à installer). L'interface est servie à la racine du site ; l'ancien gabarit et les pages statiques du volume ne
le sont plus. Aucune migration, aucune variable nouvelle. Les workers ne changent pas.

| Fait | Ressource | Réglage | Quand |
|---|---|---|---|
| ☐ | Application web | Construction plus longue (environ une minute de plus : `npm ci` et compilation de `web/`). Rien à régler ; si un délai de construction est fixé dans Coolify, le laisser à 10 minutes au moins. | — |
| ☐ | Application web | Supprimer la variable `RLPI_REPORTS` si elle existe : le serveur ne sert plus de pages statiques. | Après la fusion |
| ☐ | Volume `/app/data` (facultatif) | Le dossier `/app/data/reports/` n'est plus lu (accueil, fantôme, meilleur jeu, modèles, swipe : remplacés ou retirés, voir le journal). Il peut rester ; le supprimer libère de la place : `docker exec <conteneur web> ls /app/data/reports` pour voir, puis le supprimer par le volume (`docker run --rm -v <nom_du_volume>:/data alpine rm -rf /data/reports`). Garder `models/`, `features/`, `frames/` et `swipe/`. | Après la fusion, quand on veut |
| ☐ | Application web (contrôles) | Après la fusion : `https://rlpi.lainox.quest/` affiche la connexion Steam (navigation privée) ou le tableau de bord ; `/moi` et `/tableau_de_bord.html` redirigent vers `/ma-forme` ; une actualisation sur `/mon-jeu` ou `/matchs/<partie>` réaffiche bien la page ; `/docs` et `/ready` répondent comme avant ; `/api/inconnu` répond 404 (jamais la page de l'interface). | Après la fusion |
| ☐ | Application web (contrôle) | Nouveau match : le tableau de bord ouvert affiche « Nouveau match ajouté » et se met à jour seul quand une partie est traitée (bouton « Chercher mes nouvelles parties », puis attendre). Si rien n'arrive alors que le flux a été validé en phase E, me le signaler (l'interface interroge quand même `/api/moi` toutes les minutes si le flux est refusé). | Après la fusion |
| ☐ | Application web (contrôle) | Swipe : « Juger des actions à l'aveugle » (pied de page) → « Préparer un paquet » ; le paquet arrive en une minute environ (worker). Sans le lot de cartes SSL / RLCS (phase E), il ne contient que des actions des parties du joueur. | Après la fusion |

## Phase H — Nettoyage

Aucun réglage. Le retour de Steam refusé renvoie maintenant sur la page de connexion du site (message « La
connexion Steam n'a pas abouti ») au lieu d'une page d'erreur.

## Phase G — Déploiement et exploitation

`docs/DEPLOIEMENT_COOLIFY.md` est réécrit : c'est désormais la description complète de l'installation (services,
variables, sauvegardes, journaux, opérations courantes). Ce fichier-ci ne garde que les actions ponctuelles de
chaque fusion. Aucune migration dans cette phase.

| Fait | Ressource | Réglage | Quand |
|---|---|---|---|
| ☐ | Workers | Construction de l'image un peu plus longue : elle installe `postgresql-client-18` (pg_dump pour la sauvegarde quotidienne). Rien à régler. | — |
| ☐ | Workers (journaux) | Après la fusion, les journaux sont en JSON (une ligne par événement). Une ligne `"msg": "état"` toutes les 5 minutes (file, tâches en cours, parties bloquées, erreurs des dernières 24 h). | Après la fusion |
| ☐ | Workers | **Première sauvegarde tout de suite** (sans attendre la nuit) : `docker exec <conteneur worker> python -m rlpi.backup run`, puis `docker exec <conteneur worker> python -m rlpi.backup list` → une ligne `backups/rlpi-….dump`. En cas d'échec, me copier le message. Ensuite, une sauvegarde chaque nuit à 3 h UTC (`RLPI_BACKUP_HOUR`). | Après la fusion |
| ☐ | Postgres + worker (SSH) | **Essai de restauration** en production, sans toucher à la base en service : étapes 1 et 2 du § 5 « Restaurer » de `DEPLOIEMENT_COOLIFY.md` (base `rlpi_restauration`), puis `docker exec <conteneur postgres> psql -U <utilisateur> -d postgres -c "DROP DATABASE rlpi_restauration"`. | Après la première sauvegarde |
| ☐ | Application web (journaux) | Après la fusion, journaux en JSON : lignes Flyway (`"outil": "flyway"`), puis une ligne `"msg": "requête"` par appel avec `request_id` (aussi renvoyé dans l'en-tête `X-Request-ID`). | Après la fusion |
| ☐ | Coolify (facultatif) | Retirer les variables obsolètes si elles existent encore (liste en fin de `DEPLOIEMENT_COOLIFY.md`) ; vérifier que la limite mémoire de l'application web est d'au moins 768 Mo (phase E). | Quand on veut |
| ☐ | Coolify (facultatif) | Les journaux JSON ne changent rien au fonctionnement ; si on préfère les lire en texte : `RLPI_LOG_FORMAT=texte` sur la ressource. | — |

## Phase I — Worker, après la refonte

La migration 7 (table `dead_tasks`, tâches en « lettre morte ») passe toute seule au démarrage du nouveau conteneur
web ; les workers attendent la version 7. Aucune variable obligatoire nouvelle.

| Fait | Ressource | Réglage | Quand |
|---|---|---|---|
| ☐ | Postgres / workers | **Sauvegarde avant la migration 7** : si la phase G est déjà en service, `docker exec <conteneur worker> python -m rlpi.backup run` ; sinon (G et I fusionnées ensemble, l'ancienne image du worker n'a pas `pg_dump`), la sauvegarde manuelle comme en phase B : `docker exec <conteneur postgres> pg_dump -U <utilisateur> -Fc <base> > rlpi_avant_phase_i.dump`. | Juste avant la fusion |
| ☐ | Application web (journaux) | Après la fusion : `now at version v7` puis `Base de données en version 7`. | Après la fusion |
| ☐ | Workers (journaux) | `fin de partie` porte maintenant la durée de chaque étape (`t_replay`, `t_analyse`, `t_envoi`, `t_agregats`, détail dans `etapes`) ; la ligne `état` ajoute `parties_1h`, `duree_moy_s_1h` et `lettre_morte`. | Après la fusion |
| ☐ | Workers | Contrôle : `docker exec <conteneur worker> python -m rlpi.worker dead` → « 0 tâche(s) en attente » (les parties déjà en erreur avant la fusion n'y figurent pas ; `python -m rlpi.worker status` les liste toujours). | Après la fusion |
| ☐ | Workers (facultatif) | `RLPI_S3_PARALLEL` (défaut 8) : fichiers d'une partie téléchargés en même temps depuis Garage. Rien à changer. | — |

## Revoir une action en 3D (branche `feature/visualisation-actions-a-travailler`)

Aucune variable nouvelle, aucune migration. Les parties traitées après la fusion ont leur fichier caméras (vue
joueur du bouton « ▶ Revoir ») ; les plus anciennes le reçoivent avec la commande ci-dessous. Avant qu'elle passe,
leurs clips s'affichent quand même, avec les réglages caméra par défaut du jeu.

| Fait | Ressource | Réglage | Quand |
|---|---|---|---|
| ☐ | Workers | Rattrapage des caméras : `docker exec <conteneur worker> python -m rlpi.worker backfill-cameras`. Une partie à la fois, 2 à 4 s et environ 250 Mo chacune (dans un processus séparé, rendus à la fin), dans la mémoire du worker et jamais dans celle du serveur web. Se termine par `caméras : N déposée(s), … déjà là, … sans replay, … échec(s)`. Sans risque à relancer. | Après la fusion, une fois |
