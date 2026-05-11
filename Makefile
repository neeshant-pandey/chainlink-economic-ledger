.PHONY: help install install-airflow install-dbt install-all up down backfill \
        incremental dbt-build dbt-build-local dbt-test recon golden-walkthrough \
        idempotency-check parity test test-unit test-integration lint clean lock

RANGE ?= 18800000:18810000
TX ?=

help:
	@echo "Targets:"
	@echo "  install                Install base + dev deps"
	@echo "  install-airflow        Add Airflow deps"
	@echo "  install-dbt            Add dbt deps"
	@echo "  install-all            Install everything"
	@echo "  lock                   Refresh uv.lock from pyproject.toml"
	@echo "  up / down              Start / stop docker-compose (Airflow + Postgres)"
	@echo "  backfill RANGE=a:b     Planned live Airflow backfill for block range"
	@echo "  incremental            Planned live incremental DAG trigger"
	@echo "  dbt-build              Run full dbt build (raw -> marts) with tests"
	@echo "  dbt-build-local        Run end-to-end pipeline against local DuckDB (no cloud)"
	@echo "  dbt-test               Run dbt tests only"
	@echo "  recon                  Planned live reconciliation DAG trigger"
	@echo "  golden-walkthrough TX= Planned live forensic decode of a single tx hash"
	@echo "  idempotency-check      Planned live replay/hash-stability check"
	@echo "  parity                 Run/inspect Databricks parity check"
	@echo "  test                   Run pytest unit + integration"
	@echo "  test-unit              Run pytest unit only"
	@echo "  test-integration       Run pytest integration only"
	@echo "  lint                   static checks (ruff + mypy + sqlfluff)"

install:
	uv sync

install-airflow:
	uv sync --extra airflow

install-dbt:
	uv sync --extra dbt
	cd dbt && uv run dbt deps

install-all:
	uv sync --all-extras
	cd dbt && uv run dbt deps

lock:
	uv lock

up:
	docker-compose up -d

down:
	docker-compose down

backfill:
	uv run airflow dags trigger staking_backfill -c '{"from_block": $(word 1,$(subst :, ,$(RANGE))), "to_block": $(word 2,$(subst :, ,$(RANGE)))}'

incremental:
	uv run airflow dags trigger staking_incremental

dbt-build:
	cd dbt && uv run dbt build --target dev

dbt-build-local:
	uv run python scripts/seed_to_local.py
	uv run --extra dbt dbt seed --project-dir dbt --profiles-dir dbt --target local --full-refresh
	uv run --extra dbt dbt run --project-dir dbt --profiles-dir dbt --target local --full-refresh
	uv run --extra dbt dbt test --project-dir dbt --profiles-dir dbt --target local
	@echo
	@echo "=== local mart row counts ==="
	@uv run python -c "import duckdb; con = duckdb.connect('dbt/target/local.duckdb'); rows = con.execute(\"SELECT table_schema || '.' || table_name FROM information_schema.tables WHERE table_schema NOT IN ('information_schema','pg_catalog') ORDER BY 1\").fetchall(); [print(f'{t[0]:55s} {con.execute(f\"SELECT COUNT(*) FROM {t[0]}\").fetchone()[0]:>6} rows') for t in rows]"

dbt-test:
	cd dbt && uv run dbt test --target dev

recon:
	uv run airflow dags trigger reconciliation_check

golden-walkthrough:
	@test -n "$(TX)" || (echo "Usage: make golden-walkthrough TX=0x..." && exit 1)
	uv run python scripts/golden_tx_walkthrough.py $(TX)

idempotency-check:
	uv run python scripts/replay_partition.py --range $(RANGE) --assert-stable

parity:
	uv run python databricks/notebooks/parity_check.py

test:
	uv run pytest tests/unit -v
	uv run pytest tests/integration -v

test-unit:
	uv run pytest tests/unit -v

test-integration:
	uv run pytest tests/integration -v

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy ingestion decoder storage protocols reconciliation lineage monitoring analytics
	cd dbt && uv run sqlfluff lint || true   # sqlfluff exits non-zero on style nits; non-blocking

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
	cd dbt && rm -rf target dbt_packages logs
