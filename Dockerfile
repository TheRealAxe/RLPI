# Image de production pour Coolify : le serveur web (src/rlpi/web : API FastAPI, connexion Steam, pages) et
# l'interface Vue (web/, compilée à la construction de l'image).
# Les données ne sont PAS dans l'image : elles vivent dans le volume persistant monté sur /app/data
# (features, frames, models : références et rapports des modèles ; swipe/ : lot de cartes de référence).

# Flyway (migrations de la base, lancées au démarrage du conteneur : voir rlpi.migrate). Version notée dans
# docs/JOURNAL_REFONTE_WEB.md. On ne garde que ce qui sert à Postgres (l'image complète fait plus de 500 Mo).
FROM flyway/flyway:13.12.0 AS flyway
RUN cd /flyway && find drivers -type f ! -name 'postgresql-*.jar' -delete     && find lib/flyway -name 'flyway-database-*.jar' ! -name 'flyway-database-postgresql-*' -delete     && rm -rf lib/aad licenses

# Interface Vue (web/) compilée par Node ; seul le résultat (web/dist) passe dans l'image finale. Les jetons Plateau
# (Design/) et les polices (src/rlpi/assets/fonts) sont lus hors de web/ : une seule copie dans le dépôt.
FROM node:26.8.1-slim AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web ./
COPY Design/rlpi-plateau/design /build/Design/rlpi-plateau/design
COPY src/rlpi/assets/fonts /build/src/rlpi/assets/fonts
RUN npm run build

FROM python:3.13-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORT=3001 \
    RLPI_WEB_WORKERS=2 \
    RLPI_WEB_DIST=/app/web/dist \
    RLPI_LOG_FORMAT=json \
    RLPI_SERVICE=web

# Dépendances : seulement celles du serveur (extra « server »), versions exactes de uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /bin/uv
ENV UV_PROJECT_ENVIRONMENT=/app/.venv UV_COMPILE_BYTECODE=0 UV_LINK_MODE=copy PATH=/app/.venv/bin:$PATH
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra server && rm -rf /root/.cache

COPY --from=flyway /opt/java/openjdk /opt/java/openjdk
COPY --from=flyway /flyway /opt/flyway
ENV JAVA_HOME=/opt/java/openjdk FLYWAY_BIN=/opt/flyway/flyway RLPI_MIGRATIONS=/app/migrations

COPY config ./config
COPY migrations ./migrations
COPY src ./src
COPY --from=web /build/web/dist ./web/dist

# Plus de cache sur disque : le contenu vient des agrégats en base (gardé en mémoire par rlpi.web.cache).
# Le volume /app/data peut appartenir à root.
RUN useradd --create-home app && mkdir -p /app/data && chown -R app:app /app/data
USER app

EXPOSE 3001
HEALTHCHECK --interval=30s --timeout=3s --start-period=90s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3001/health', timeout=2)" || exit 1
# Migrations d'abord (Flyway, verrou contre les lancements simultanés) ; si elles échouent, le conteneur ne démarre
# pas et Coolify garde l'ancienne version en service. Puis uvicorn avec RLPI_WEB_WORKERS processus (2 par défaut),
# sans son journal d'accès (il écrirait les paramètres des adresses) : rlpi.web écrit le sien. Journaux en JSON
# (rlpi.logs ; config/journal_uvicorn.json pour ceux d'uvicorn), lisibles dans Coolify.
CMD ["sh", "-c", "python -m rlpi.migrate && exec uvicorn --factory rlpi.web.main:create_app --host 0.0.0.0 --port \"$PORT\" --workers \"$RLPI_WEB_WORKERS\" --no-access-log --log-config /app/config/journal_uvicorn.json --timeout-graceful-shutdown 5"]
