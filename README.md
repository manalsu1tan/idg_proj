# Project B: Hierarchical Memory for Generative Agents

This repository implements a research-first memory systems stack for generative agents. It preserves the dissertation-style `observe -> retrieve -> plan/react/reflect -> write back` loop while replacing the flat memory stream with a traceable L0/L1 hierarchy.

## What is implemented

- Flat-memory baseline with heuristic retrieval over recency, relevance, and importance.
- Hierarchical L0/L1 memory tree with summary generation, provenance, versioning, and staleness tracking.
- Top-down retrieval with selective leaf descent and token-budgeted context packing.
- Summary verification and refresh policy hooks.
- Synthetic evaluation harness that compares the flat baseline against the hierarchical system.
- FastAPI service exposing ingest, retrieve, summarize, refresh, provenance, timeline, and eval endpoints.

## Local development

```bash
./scripts/bootstrap_uv.sh
source .venv/bin/activate
alembic upgrade head
uvicorn apps.api.main:app --reload
```

The default runtime uses a local SQLite database so the repository is runnable in constrained environments. Production-oriented configuration for `PostgreSQL + pgvector` and `Redis` is included under [`infra/docker-compose.yml`](/Users/Manal/Documents/GitHub/idg_proj/infra/docker-compose.yml).

If you prefer `uv`, the bootstrap script is [`bootstrap_uv.sh`](/Users/Manal/Documents/GitHub/idg_proj/scripts/bootstrap_uv.sh). It installs the default dev stack plus Postgres and worker dependencies. Pass `--train` to include the heavier training extras.

Local `.env` files are auto-loaded from the repo root by [`settings.py`](/Users/Manal/Documents/GitHub/idg_proj/packages/memory_core/settings.py:1). Explicit shell environment variables still take precedence.

To validate the real Postgres path end-to-end, use [`validate_postgres_stack.sh`](/Users/Manal/Documents/GitHub/idg_proj/scripts/validate_postgres_stack.sh). It starts `postgres` and `redis`, waits for readiness, runs `alembic upgrade head` against Postgres, and verifies that the `vector` extension is enabled.

```bash
./scripts/validate_postgres_stack.sh
```

Use `--with-api` if you want it to launch the API after migrations succeed.

To seed benchmark agents into the configured database for the inspector UI, use [`seed_benchmark_agents.sh`](/Users/Manal/Documents/GitHub/idg_proj/scripts/seed_benchmark_agents.sh):

```bash
./scripts/seed_benchmark_agents.sh --reset
```

This seeds:

- `benchmark-agent-delayed-commitment`
- `benchmark-agent-routine-interruption`

## Real model provider

The repository now targets a real OpenAI-compatible endpoint by default in `.env.example`.

- `PROJECT_B_MODEL_PROVIDER=openai_compatible`
- `PROJECT_B_MODEL_BASE_URL=https://api.openai.com/v1`
- `PROJECT_B_MODEL_API_KEY=...`

The structured summarizer and verifier use the Responses API with JSON Schema constrained outputs. For isolated tests or offline work, set `PROJECT_B_MODEL_PROVIDER=mock`.

Example local `.env`:

```env
PROJECT_B_MODEL_PROVIDER=openai_compatible
PROJECT_B_MODEL_BASE_URL=https://api.openai.com/v1
PROJECT_B_MODEL_API_KEY=your_key_here
PROJECT_B_DATABASE_URL=postgresql+psycopg://project_b:project_b@localhost:5432/project_b
PROJECT_B_AUTO_CREATE_SCHEMA=false
```

## Database and migrations

- Local fallback: `PROJECT_B_DATABASE_URL=sqlite+pysqlite:///./project_b.db`
- Production target: `PROJECT_B_DATABASE_URL=postgresql+psycopg://project_b:project_b@localhost:5432/project_b`
- Migration entrypoint: [`alembic.ini`](/Users/Manal/Documents/GitHub/idg_proj/alembic.ini)
- Initial schema migration: [`20250317_000001_initial_schema.py`](/Users/Manal/Documents/GitHub/idg_proj/alembic/versions/20250317_000001_initial_schema.py)

The app can still auto-create schema for local test workflows, but production should run `alembic upgrade head` before serving traffic.

## Inspector UI

The read-only inspection surface is served directly by FastAPI at `/ui`. It visualizes:

- agent timeline
- L0/L1 memory tree
- node provenance
- retrieval traces
- model traces
- eval history

## Layout

- [`apps/api/main.py`](/Users/Manal/Documents/GitHub/idg_proj/apps/api/main.py): FastAPI entrypoint.
- [`apps/ui/static/index.html`](/Users/Manal/Documents/GitHub/idg_proj/apps/ui/static/index.html): minimal inspector UI.
- [`apps/worker/worker.py`](/Users/Manal/Documents/GitHub/idg_proj/apps/worker/worker.py): async job hooks for summarization, refresh, and verification.
- [`packages/memory_core/services.py`](/Users/Manal/Documents/GitHub/idg_proj/packages/memory_core/services.py): orchestration layer for baseline and hierarchical memory flows.
- [`packages/memory_core/model_components.py`](/Users/Manal/Documents/GitHub/idg_proj/packages/memory_core/model_components.py): model-backed summarizer and verifier.
- [`packages/evals/runner.py`](/Users/Manal/Documents/GitHub/idg_proj/packages/evals/runner.py): deterministic benchmark harness.
