#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but was not found on PATH."
  echo "Install it first: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

INSTALL_TRAINING=0
SYNC_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      echo "Usage: scripts/bootstrap_uv.sh [--train] [--sync-only]"
      echo
      echo "  --train      Include training dependencies."
      echo "  --sync-only  Skip uv venv creation and only run uv sync."
      exit 0
      ;;
    --train)
      INSTALL_TRAINING=1
      shift
      ;;
    --sync-only)
      SYNC_ONLY=1
      shift
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: scripts/bootstrap_uv.sh [--train] [--sync-only]"
      exit 1
      ;;
  esac
done

EXTRAS=(--extra dev --extra postgres --extra worker)
if [[ "$INSTALL_TRAINING" -eq 1 ]]; then
  EXTRAS+=(--extra train)
fi

if [[ "$SYNC_ONLY" -ne 1 ]]; then
  echo "Creating virtual environment with uv..."
  uv venv
fi

echo "Syncing project dependencies..."
uv sync "${EXTRAS[@]}"

cat <<'EOF'

Dependency bootstrap complete.

Next steps:
  1. source .venv/bin/activate
  2. cp .env.example .env
  3. alembic upgrade head
  4. uv run uvicorn apps.api.main:app --reload

Optional:
  - Add --train to include PyTorch / training dependencies.
  - Use --sync-only if the virtualenv already exists.
EOF
