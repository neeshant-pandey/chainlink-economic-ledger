#!/usr/bin/env bash
# One-command reproduction (the fixture reproduction path).
#
# Two modes:
#   --fixture-only   — runs unit tests + dbt parse using cached fixtures (no
#                      live RPC/BQ). The local reproducibility proof.
#   (default)        — full live pipeline (requires RPC_URL + GCP_PROJECT).

set -euo pipefail

MODE="${1:-live}"

cd "$(dirname "$0")/.."

if [[ "$MODE" == "--fixture-only" ]]; then
    echo "==> Running --fixture-only repro (no live access)"

    # Phase 1: unit tests against cached golden fixtures
    echo "==> [1/3] pytest tests/unit"
    uv run pytest tests/unit -v

    # Phase 2: dbt parse (validates all SQL compiles)
    echo "==> [2/3] dbt parse"
    GCP_PROJECT="${GCP_PROJECT:-test-proj}" \
        uv run --extra dbt dbt parse \
        --project-dir dbt --profiles-dir dbt --target ci

    # Phase 3: idempotency replay test
    echo "==> [3/4] replay-idempotency"
    uv run pytest tests/unit/test_replay_idempotency.py tests/unit/test_id_determinism.py -v

    # Phase 4: analytics-refs sanity
    echo "==> [4/4] analytics SQL-ref enforcement"
    uv run python scripts/check_analytics_refs.py

    echo "==> --fixture-only repro PASSED"
    exit 0
fi

# Default: live pipeline reproduction (requires RPC + GCP)
RANGE="${RANGE:-18800000:18810000}"
FROM_BLOCK="${RANGE%:*}"
TO_BLOCK="${RANGE#*:}"

echo "==> Live repro for blocks ${FROM_BLOCK}..${TO_BLOCK}"

# 1. Local infra
docker-compose up -d
echo "==> Airflow + Postgres up. Waiting for scheduler readiness..."
sleep 10

# 2. Backfill
make backfill RANGE="${RANGE}"

# 3. dbt build (raw → marts)
make dbt-build

# 4. Reconciliation report
make recon

# 5. Idempotency check
make idempotency-check RANGE="${RANGE}"

# 6. Print result paths
echo "==> Done. Inspect:"
echo "    BigQuery dataset: ${BQ_DATASET_MARTS:-staking_marts}"
echo "    Reconciliation status: SELECT * FROM \`${GCP_PROJECT}.${BQ_DATASET_MARTS:-staking_marts}.reconciliation_status\`"
