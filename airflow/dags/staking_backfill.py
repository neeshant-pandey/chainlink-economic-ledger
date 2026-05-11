"""Historical backfill DAG.

Triggered with config `{"from_block": int, "to_block": int}`. Splits the range
into block-day partitions and processes each as an independent task group so
partial failures don't block neighbors.

Task graph (per partition):
    extract_blocks  → extract_logs  → extract_receipts  → load_raw_to_bq
                   ↓
                   extract_traces (only for slashing/migration/unmatched txs)
                   ↓
    decode_python  → write_decoded_parquet  → load_decoded_to_bq
                   ↓
    reconcile_python → write_recon_parquet  → load_recon_to_bq
                   ↓
    dbt_run (raw → staging → intermediate → marts)
                   ↓
    dbt_test
"""

from __future__ import annotations

# ruff: noqa  # imports kept symbolic until DAG body is implemented

# from datetime import datetime
# from airflow import DAG
# from airflow.operators.bash import BashOperator
# from airflow.operators.python import PythonOperator
# from airflow.providers.google.cloud.operators.bigquery import BigQueryInsertJobOperator
#
# from operators.evm_log_extract_operator import EvmLogExtractOperator
# from operators.evm_trace_extract_operator import EvmTraceExtractOperator
# from operators.evm_balance_snapshot_operator import EvmBalanceSnapshotOperator


def build_backfill_dag():
    """Returns the Airflow DAG object.

    Implementation contract:
      - DAG id: 'staking_backfill'
      - Catchup: False; this DAG runs on-demand, not on a schedule
      - Max active runs: 1
      - Task groups: one per block-day partition
      - All operators emit GCS manifest paths via XCom; never raw data rows
      - dbt invocations use BashOperator (`dbt build --select state:modified+`)
      - Failure policy: a partition failure marks downstream as failed but does
        not block neighboring partitions
    """
    raise NotImplementedError(
        "Planned production DAG: historical backfill wiring requires a live Airflow "
        "environment plus BigQuery/GCS credentials."
    )


# Module-level DAG export expected by Airflow scheduler. Uncomment when implemented.
# dag = build_backfill_dag()
