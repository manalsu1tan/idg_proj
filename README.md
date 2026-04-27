# Hierarchical Memory for Generative Agents

A memory architecture for generative agents, testing whether a hierarchical, provenance preserving memory system supports better retrieval and more useful state abstraction than a flat episodic memory stream alone.

The system keeps the familiar agent loop of `observe -> retrieve -> plan/react/reflect -> write back`, but replaces a flat memory log with a traceable L0/L1 hierarchy:

- L0 nodes store timestamped episodic memories and metadata.
- L1 summaries compress related episodes while preserving support links.
- Retrieval can run either as a flat baseline or through the hierarchy.
- Model backed summarization, verification, and answer generation are traced for inspection.
- Evaluation compares hierarchical retrieval against the flat baseline on seeded behavioral memory tasks.

## Project Overview

The final report is [idg_proj/m_report_final.pdf](/Users/Manal/Documents/GitHub/idg_proj/m_report_final.pdf)

The repository combines an agent memory service, an inspection UI, and an evaluation harness.

- Memory ingestion writes raw episodes into a structured store with timestamps, entities, topics, and provenance.
- Summary building clusters related L0 memories into verified L1 summaries with versioning and staleness tracking.
- Retrieval supports both a flat memory baseline and a hierarchical retriever with selective leaf descent and token budgeted context packing.
- Verification keeps summary quality checks and answer checks separate from generation.
- Social state derivation compresses memory into higher level categories such as commitments, revisions, tensions, and relationship guidance.
- Counterfactual replay reruns scenarios under local edits to compare how memory and retrieval behavior change.
- Evaluation runs seeded benchmarks, ablations, and larger policy sweeps, then exports JSON and Markdown reports.

## Codebase Overview

The repository is organized into three main layers: API and UI entrypoints, core memory services, and evaluation tooling.

### Main application entrypoints

- [apps/api/main.py](/Users/Manal/Documents/GitHub/idg_proj/apps/api/main.py): FastAPI app exposing ingest, retrieve, summarize, refresh, provenance, timeline, trace, eval, ablation, and counterfactual endpoints.
- [apps/ui/static/index.html](/Users/Manal/Documents/GitHub/idg_proj/apps/ui/static/index.html): read-only inspection UI served at `/ui`.
- [apps/worker/worker.py](/Users/Manal/Documents/GitHub/idg_proj/apps/worker/worker.py): worker hooks for summarization, refresh, and verification flows.

### Core memory system

- [packages/memory_core/services.py](/Users/Manal/Documents/GitHub/idg_proj/packages/memory_core/services.py): orchestration layer for ingest, tree building, flat retrieval, hierarchical retrieval, refresh, and inspection views.
- [packages/memory_core/model_components.py](/Users/Manal/Documents/GitHub/idg_proj/packages/memory_core/model_components.py): model backed summarizer, verifier, answerer, and answer verifier components.
- [packages/memory_core/social_state.py](/Users/Manal/Documents/GitHub/idg_proj/packages/memory_core/social_state.py): social state digest derivation over stored memory.
- [packages/memory_core/storage.py](/Users/Manal/Documents/GitHub/idg_proj/packages/memory_core/storage.py): persistence layer for nodes, traces, eval runs, and supporting state.
- [packages/memory_core/settings.py](/Users/Manal/Documents/GitHub/idg_proj/packages/memory_core/settings.py): runtime configuration and `.env` loading.

### Evaluation and reporting

- [packages/evals/runner.py](/Users/Manal/Documents/GitHub/idg_proj/packages/evals/runner.py): deterministic benchmark runner.
- [packages/evals/ablation.py](/Users/Manal/Documents/GitHub/idg_proj/packages/evals/ablation.py): retrieval regime ablations and report generation.
- [packages/evals/counterfactual.py](/Users/Manal/Documents/GitHub/idg_proj/packages/evals/counterfactual.py): counterfactual replay evaluation.
- [packages/evals/report.py](/Users/Manal/Documents/GitHub/idg_proj/packages/evals/report.py): benchmark report payloads and Markdown rendering.
- [reports/](/Users/Manal/Documents/GitHub/idg_proj/reports): generated evaluation, ablation, and frontier artifacts.

### Infrastructure and scripts

- [infra/docker-compose.yml](/Users/Manal/Documents/GitHub/idg_proj/infra/docker-compose.yml): local Postgres, pgvector, and Redis stack.
- [scripts/bootstrap_uv.sh](/Users/Manal/Documents/GitHub/idg_proj/scripts/bootstrap_uv.sh): environment bootstrap for local development.
- [scripts/validate_postgres_stack.sh](/Users/Manal/Documents/GitHub/idg_proj/scripts/validate_postgres_stack.sh): end to end Postgres migration validation.
- [scripts/seed_benchmark_agents.sh](/Users/Manal/Documents/GitHub/idg_proj/scripts/seed_benchmark_agents.sh): seed demo and benchmark agents for the inspector UI.
- [scripts/export_benchmark_report.sh](/Users/Manal/Documents/GitHub/idg_proj/scripts/export_benchmark_report.sh): export benchmark reports from stored eval runs.
- [scripts/export_ablation_report.sh](/Users/Manal/Documents/GitHub/idg_proj/scripts/export_ablation_report.sh): run ablations and export reports.
- [scripts/run_frontier_sweep.sh](/Users/Manal/Documents/GitHub/idg_proj/scripts/run_frontier_sweep.sh): run larger retrieval policy sweeps and export frontier artifacts.
- [scripts/plot_frontier_results.py](/Users/Manal/Documents/GitHub/idg_proj/scripts/plot_frontier_results.py): plotting utility for frontier outputs.

## How To Run

The simplest path uses the default local SQLite runtime. The full stack uses Postgres, pgvector, and Redis.

### Quick start with local SQLite

```bash
./scripts/bootstrap_uv.sh
source .venv/bin/activate
uv run alembic upgrade head
uv run uvicorn apps.api.main:app --reload
```

This starts the API on the default Uvicorn port and uses the local SQLite fallback database at `project_b.db`.

Once the server is running:

- API docs are available at `http://127.0.0.1:8000/docs`
- the inspector UI is available at `http://127.0.0.1:8000/ui`

Local `.env` files are auto loaded from the repository root by [packages/memory_core/settings.py](/Users/Manal/Documents/GitHub/idg_proj/packages/memory_core/settings.py). Explicit shell environment variables still take precedence.

### Run with Postgres, pgvector, and Redis

If you want to validate the real database path instead of the SQLite fallback:

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis

export PROJECT_DATABASE_URL=postgresql+psycopg://project_b:project_b@localhost:5432/project_b
export PROJECT_AUTO_CREATE_SCHEMA=false

uv run alembic upgrade head
uv run uvicorn apps.api.main:app --reload
```

You can confirm service readiness with:

```bash
docker compose -f infra/docker-compose.yml ps
```

If you want a one-command validation of the Postgres path, use:

```bash
./scripts/validate_postgres_stack.sh
```

Use `--with-api` if you want that script to launch the API after migrations succeed.

To stop the local Postgres stack later:

```bash
docker compose -f infra/docker-compose.yml down
```

### Model provider configuration

The repository is configured to support an OpenAI endpoint.

- `PROJECT_MODEL_PROVIDER=openai_compatible`
- `PROJECT_MODEL_BASE_URL=https://api.openai.com/v1`
- `PROJECT_MODEL_API_KEY=...`

For isolated tests or offline development, set:

```env
PROJECT_MODEL_PROVIDER=mock
```

Example `.env` for a local Postgres backed run:

```env
PROJECT_MODEL_PROVIDER=openai_compatible
PROJECT_MODEL_BASE_URL=https://api.openai.com/v1
PROJECT_MODEL_API_KEY=your_key_here
PROJECT_DATABASE_URL=postgresql+psycopg://project_b:project_b@localhost:5432/project_b
PROJECT_AUTO_CREATE_SCHEMA=false
```

## Running Benchmarks And Reports

### Seed benchmark agents for the UI

```bash
./scripts/seed_benchmark_agents.sh --reset
```

This seeds:

- `benchmark-agent-delayed-commitment`
- `benchmark-agent-routine-interruption`
- `benchmark-agent-relationship-context`
- `benchmark-agent-commitment-revision`
- `benchmark-agent-identity-shift`

### Export the standard benchmark report

```bash
./scripts/export_benchmark_report.sh
```

This writes JSON and Markdown artifacts under [reports/](/Users/Manal/Documents/GitHub/idg_proj/reports).

### Run retrieval ablations

```bash
./scripts/export_ablation_report.sh
```

### Run a larger frontier sweep

```bash
PROJECT_MODEL_PROVIDER=mock ./scripts/run_frontier_sweep.sh --max-candidates 200 --sample-method lhs
```

The frontier sweep optimizes over multi-slice objectives by default:

- canonical seeds
- unseen seeds with `+100` offsets
- hard query perturbations such as `concise`, `indirect`, `colloquial`, `typo_noise`, `word_order`, and `entity_swap_distractor`
- family-level objectives such as `multi_person_interference` slot gain and `time_window_pressure` token delta

Generated frontier outputs are written under [reports/](/Users/Manal/Documents/GitHub/idg_proj/reports).

## Database Notes

- Local fallback: `sqlite+pysqlite:///./project_b.db`
- Production oriented local stack: `postgresql+psycopg://project_b:project_b@localhost:5432/project_b`
- Migration entrypoint: [alembic.ini](/Users/Manal/Documents/GitHub/idg_proj/alembic.ini)
- Migrations live under [alembic/versions](/Users/Manal/Documents/GitHub/idg_proj/alembic/versions)

The app can auto create schema for lightweight local workflows, but production oriented runs should use:

```bash
uv run alembic upgrade head
```

before serving traffic.

If Postgres is unavailable and `PROJECT_DATABASE_FALLBACK_ON_UNAVAILABLE=true`, the service may fall back to `project_b.db`, which should not be treated as a substitute for validating the real Postgres path.
