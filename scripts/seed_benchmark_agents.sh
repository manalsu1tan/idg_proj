#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but was not found on PATH."
  exit 1
fi

export PROJECT_B_DATABASE_URL="${PROJECT_B_DATABASE_URL:-postgresql+psycopg://project_b:project_b@localhost:5432/project_b}"
export PROJECT_B_AUTO_CREATE_SCHEMA="${PROJECT_B_AUTO_CREATE_SCHEMA:-false}"

uv run python -m packages.evals.seed "$@"
