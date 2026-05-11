"""Replay a block range and assert mart-hash stability.

Computes a fresh `run_partition_id`, deletes the BQ/GCS rows for the range,
re-runs ingestion → decode → reconcile → dbt, and compares mart hashes before
and after. Mart unique keys are stable entity IDs, so replay overwrites in
place; hashes are computed excluding `run_partition_id`.

Usage:
    python scripts/replay_partition.py --range 18800000:18810000 --assert-stable
"""

from __future__ import annotations


def main() -> int:
    raise NotImplementedError(
        "Planned live-runtime script: replay requires BigQuery/GCS deletion, "
        "Airflow backfill triggering, and mart hash comparison in a cloud project."
    )


if __name__ == "__main__":
    raise SystemExit(main())
