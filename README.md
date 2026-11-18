# RLPI v2 — Rocket League Player Index

Notation de joueurs Rocket League à partir de leurs replays : critères mesurés automatiquement et score
d'adéquation des décisions, appris sur des matchs de haut niveau. Le site (https://rlpi.lainox.quest) montre à
chaque joueur, après connexion Steam, le tableau de bord de ses parties récupérées sur ballchasing.com.

## Architecture

Le worker calcule, l'API sert, le navigateur affiche.

```
Navigateur (Vue 3, web/) ──/api/… JSON──► FastAPI (src/rlpi/web, uvicorn) ──► Postgres (comptes, parties, agrégats)
                                                                         └─► Redis (file, événements)
Worker (src/rlpi/worker.py) : Redis → analyse de la partie (rlpi.game) → Garage (S3) → agrégats dans Postgres
```

- `src/rlpi/dashboard/` : calcul du tableau de bord (agrégats par partie, références SSL / RLCS, contenu).
- `src/rlpi/web/` : API, connexion Steam, sessions, interface compilée servie à la racine.
- `web/` : interface (onglets Ma forme, Matchs, Mon jeu, À travailler, Mon trio, Tous les indicateurs ; Les
  modèles ; swipe).
- `migrations/` : schéma de la base (Flyway). `scripts/` : remplissage local, jeu d'essai, export de l'OpenAPI.

## Environnement de développement local

Prérequis : Docker Desktop, [uv](https://docs.astral.sh/uv/), le dossier de données de travail `rlpi-data-lainox/`
(non versionné) et, pour tester la recherche de nouvelles parties, un `.env` avec `BALLCHASING_TOKEN` (voir
`.env.example`).

```bash
uv sync --all-extras                                      # dépendances verrouillées (uv.lock) + outils de dev
docker compose -f docker-compose.dev.yml up -d --build    # Postgres, Redis, Garage, serveur, worker
.venv/Scripts/python scripts/dev_setup.py                 # Garage + parties de rlpi-data-lainox/ (sans ballchasing)
```

Compter une dizaine de minutes la première fois (construction des images, surtout celle du worker).

- Site : http://localhost:3001 ; en local, la page de connexion propose aussi d'entrer sans Steam pour n'importe
  quel joueur déjà présent dans les parties (`RLPI_DEV_LOGIN=1`, refusé par le serveur en `https://`)
- Traiter des replays : `docker compose -f docker-compose.dev.yml exec worker python -m rlpi.worker enqueue /replays/*.replay`
  (`/replays` = `data/raw/`)
- État du worker : `docker compose -f docker-compose.dev.yml exec worker python -m rlpi.worker status`
- Tout effacer : `docker compose -f docker-compose.dev.yml down -v`

En local, pas de recherche automatique sur ballchasing (`RLPI_SYNC_MINUTES=0`) et 5 parties au plus au premier
passage d'un joueur : le bouton « Chercher mes nouvelles parties » lance une vraie recherche.

## Interface

```bash
cd web && npm ci            # une fois (Node 26)
npm run dev                 # http://localhost:5173, l'API étant celle de docker-compose (port 3001)
npm run test && npx vue-tsc --noEmit
```

Après un changement d'API : `uv run python scripts/export_openapi.py` puis `npm run api-types` (met à jour
`web/src/api/schema.d.ts`, versionné ; la CI vérifie qu'il est à jour). L'image du serveur compile `web/` elle-même.

## Tests

```bash
uv run pytest                                             # sans base : les tests Postgres sont sautés
RLPI_TEST_DATABASE_URL=postgresql://rlpi:rlpi@127.0.0.1:5432/rlpi uv run pytest   # avec le Postgres local
uv run ruff check && uv run pyright                       # lint et types (comme la CI)
```

- `127.0.0.1` et non `localhost` (sous Windows, `localhost` part en IPv6 et bloque).
- `tests/test_snapshot.py` compare le contenu du tableau de bord calculé sur le jeu d'essai (`tests/fixtures/`,
  anonymisé, fabriqué par `scripts/make_fixtures.py`) à un instantané : les chiffres ne doivent pas bouger pendant
  la refonte. Changement voulu des indicateurs : `uv run pytest tests/test_snapshot.py --update-snapshot`, et
  noter la raison dans le journal.
- Tableau de bord : le worker calcule les agrégats de chaque partie (`src/rlpi/dashboard/aggregate.py`), le serveur
  les lit dans Postgres et calcule le contenu (`content.py`). Changer un calcul par partie : augmenter
  `aggregate.VERSION` ; au démarrage, un worker remet en file les parties concernées
  (`python -m rlpi.worker rebuild-aggregates` pour le faire à la demande).
- Schéma de la base : fichiers SQL de `migrations/` (Flyway). État local :
  `docker compose -f docker-compose.dev.yml run --rm flyway info`.

## Documentation

- `CLAUDE.md` : contexte et règles de travail
- `docs/PLAN.md` et `docs/JOURNAL.md` : modèles et indicateurs
- `docs/PLAN_REFONTE_WEB.md` et `docs/JOURNAL_REFONTE_WEB.md` : refonte de l'application web
- `docs/DEPLOIEMENT_COOLIFY.md` et `docs/REGLAGES_COOLIFY.md` : production
- `config/criteres_rlpi.yaml` : les 20 critères et leur source en v2
- `docs/historique/RLPI_2020.xlsx` : le fichier d'origine
