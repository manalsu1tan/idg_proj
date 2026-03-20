PYTHON ?= python3

.PHONY: bootstrap validate-postgres seed-benchmarks test run-api run-eval migrate upgrade head

bootstrap:
	./scripts/bootstrap_uv.sh

validate-postgres:
	./scripts/validate_postgres_stack.sh

seed-benchmarks:
	./scripts/seed_benchmark_agents.sh --reset

test:
	$(PYTHON) -m pytest

run-api:
	uvicorn apps.api.main:app --reload

run-eval:
	$(PYTHON) -m packages.evals.runner

migrate:
	alembic upgrade head
