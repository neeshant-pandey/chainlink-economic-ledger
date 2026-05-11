"""Small-range end-to-end backfill: ingestion → decode → reconcile → dbt build → recon."""

import pytest

pytestmark = pytest.mark.integration


def test_backfill_small_range_end_to_end() -> None:
    """Small-range end-to-end backfill against live BigQuery + Airflow.

    Asserts: canonical_blocks rows == 100; ≥1 decoded staking event;
    reconciliation_status row written; no critical CheckResult failures; mart
    contracts validated by dbt build.
    """
    pytest.skip(
        "Integration test — requires live BigQuery runtime (paid-tier writes) "
        "and Airflow scheduler. Documented as Phase 6 stretch in "
        "docs/reproduction.md. Unit-level coverage of the same logic lives in "
        "tests/unit/test_golden_stake_decoding.py and the dbt build path is "
        "exercised end-to-end via `make dbt-build-local` against DuckDB."
    )
