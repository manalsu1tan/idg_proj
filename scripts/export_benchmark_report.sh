#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

export PROJECT_DATABASE_URL="${PROJECT_DATABASE_URL:-postgresql+psycopg://project_b:project_b@localhost:5432/project_b}"
export PROJECT_AUTO_CREATE_SCHEMA="${PROJECT_AUTO_CREATE_SCHEMA:-false}"

python -m packages.evals.report "$@"
