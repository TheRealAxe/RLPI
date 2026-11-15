# Image de production pour Coolify : le serveur du tableau de bord (src/rlpi/serve.py).
# Les données ne sont PAS dans l'image : elles vivent dans le volume persistant monté sur /app/data
# (features, frames, models, et les pages statiques dans /app/data/reports).
FROM python:3.13-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    RLPI_HOST=0.0.0.0 \
    PORT=3001 \
    RLPI_REPORTS=/app/data/reports \
    RLPI_USERS_CACHE=/app/cache

# Seulement ce que le serveur utilise (pas de collecte ni de parsing en production).
# boto3, redis, psycopg : version multi-joueurs (stockage S3, file Redis, comptes Postgres ; voir rlpi.account).
RUN pip install --no-cache-dir "polars>=2.1" "pyarrow>=20" "numpy>=2" "python-dotenv>=1.2" "pyyaml>=6" "boto3>=1.35" "redis>=5" "psycopg[binary]>=3.2"

COPY config ./config
COPY src ./src

# /app/cache : parties des joueurs rassemblées depuis le stockage (rlpi.players). Recréé à partir de Garage si
# perdu (redéploiement) ; on peut y monter un volume pour le garder. Le volume /app/data peut appartenir à root.
RUN useradd --create-home app && mkdir -p /app/data/reports /app/cache && chown -R app:app /app/data /app/cache
USER app

EXPOSE 3001
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3001/health', timeout=2)" || exit 1
CMD ["python", "-m", "rlpi.serve"]
