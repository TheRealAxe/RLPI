#!/usr/bin/env bash
# Lance le serveur web en local (python -m rlpi.web), hors Docker, sur http://127.0.0.1:8765.
# Postgres, Redis et Garage tournent dans Docker (docker-compose.dev.yml), démarrés ici s'ils ne le sont pas.
#
#   bash scripts/serveur_dev.sh [--port 8765]
#
# Valeurs de développement seulement (les mêmes que docker-compose.dev.yml). Ctrl+C pour arrêter.
set -euo pipefail

cd "$(dirname "$0")/.."
# Chemin Windows (D:/Dev/RLPI) sous Git Bash, pour que Python le comprenne
ROOT="$(pwd -W 2>/dev/null || pwd)"

docker compose -f docker-compose.dev.yml up -d postgres redis garage flyway

export DATABASE_URL="postgresql://rlpi:rlpi@127.0.0.1:5432/rlpi"
export REDIS_URL="redis://127.0.0.1:6379/0"
export S3_ENDPOINT="http://127.0.0.1:3900"
export S3_ACCESS_KEY="GKb56db53a9f4c57c9ac99c9b6"
export S3_SECRET_KEY="753906dc8f3f63bc92b6592df7eb33b30892406c383742bb308691970f5382b7"
export S3_BUCKET="rlpi"
export S3_REGION="garage"
export RLPI_SECRET="dev-seulement-0123456789abcdef0123456789abcdef"
export RLPI_DEV_LOGIN="1"
export RLPI_DATA="$ROOT/rlpi-data-lainox"
export PYTHONUNBUFFERED=1

PORT=8765
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  [[ "${args[i]}" == "--port" ]] && PORT="${args[i + 1]}"
done
export RLPI_PUBLIC_URL="http://127.0.0.1:$PORT"

if [[ -x .venv/Scripts/python.exe ]]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
echo "Connexion sans Steam : $RLPI_PUBLIC_URL/dev/connexion"
exec "$PY" -m rlpi.web --port "$PORT"
