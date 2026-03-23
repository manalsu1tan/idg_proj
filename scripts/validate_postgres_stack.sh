#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but was not found on PATH."
  exit 1
fi

START_API=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-api)
      START_API=1
      shift
      ;;
    -h|--help)
      echo "Usage: scripts/validate_postgres_stack.sh [--with-api]"
      echo
      echo "  --with-api  Start the API after migrations and validation succeed."
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: scripts/validate_postgres_stack.sh [--with-api]"
      exit 1
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required but was not found on PATH."
  exit 1
fi

COMPOSE_CMD="docker compose"
if ! $COMPOSE_CMD version >/dev/null 2>&1; then
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
  else
    echo "docker compose or docker-compose is required."
    exit 1
  fi
fi

echo "Starting postgres and redis containers..."
$COMPOSE_CMD -f infra/docker-compose.yml up -d postgres redis

echo "Waiting for Postgres readiness..."
for _ in {1..30}; do
  if $COMPOSE_CMD -f infra/docker-compose.yml exec -T postgres pg_isready -U project_b -d project_b  >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! $COMPOSE_CMD -f infra/docker-compose.yml exec -T postgres pg_isready -U project_b -d project_b >/dev/null 2>&1; then
  echo "Postgres did not become ready in time."
  exit 1
fi

export PROJECT_DATABASE_URL="postgresql+psycopg://project_b:project_b@localhost:5432/project_b"
export PROJECT_AUTO_CREATE_SCHEMA="false"

echo "Running Alembic migrations against Postgres..."
uv run alembic upgrade head

echo "Validating pgvector extension..."
$COMPOSE_CMD -f infra/docker-compose.yml exec -T postgres psql -U project_b -d project_b -tAc \
  "SELECT extname FROM pg_extension WHERE extname = 'vector';" | grep -qx "vector"

echo "Validating migrated tables..."
$COMPOSE_CMD -f infra/docker-compose.yml exec -T postgres psql -U project_b -d project_b -tAc \
  "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('memory_nodes','memory_edges','retrieval_traces','model_traces','eval_runs') ORDER BY table_name;"

echo
echo "Postgres migration validation succeeded."
echo "Database URL: $PROJECT_DATABASE_URL"

if [[ "$START_API" -eq 1 ]]; then
  echo "Starting API with Postgres configuration..."
  uv run uvicorn apps.api.main:app --reload
fi
