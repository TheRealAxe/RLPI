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
    RLPI_REPORTS=/app/data/reports

# Seulement ce que le serveur utilise (pas de collecte ni de parsing en production)
RUN pip install --no-cache-dir "polars>=2.1" "pyarrow>=20" "numpy>=2" "python-dotenv>=1.2" "pyyaml>=6"

COPY config ./config
COPY src ./src

RUN useradd --create-home app && mkdir -p /app/data/reports && chown -R app:app /app/data
USER app

EXPOSE 3001
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3001/health', timeout=2)" || exit 1
CMD ["python", "-m", "rlpi.serve"]
