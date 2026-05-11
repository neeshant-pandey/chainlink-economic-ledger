"""Near-real-time incremental DAG.

Schedule: every 10 minutes. Each run advances the checkpoint forward by the
finality watermark, processing only blocks that became finalized since the
previous run.

Task graph:
    detect_reorg_against_checkpoint
       ↓ (if reorg) mark_partition_for_replay → return
       ↓ (else)
    extract_logs (from checkpoint+1 to safe_to_block)
       ↓
    extract_receipts (for the txs in those logs)
       ↓
    extract_traces_selective (only slashing/migration/unmatched-flagged txs)
       ↓
    decode + reconcile (Python tasks)
       ↓
    load to BQ + dbt run + dbt test (incremental selectors only)
       ↓
    advance_checkpoint
"""

from __future__ import annotations

# ruff: noqa


def build_incremental_dag():
    """Implementation contract:
    - DAG id: 'staking_incremental'
    - Schedule: '*/10 * * * *'  (every 10 min)
    - Catchup: False
    - SLA: 30 min (alert via reconciliation_check DAG, not here)
    - Max active runs: 1
    - First task: detect_canonical_conflict against last_processed_block_hash
      from the Checkpoint store
    - Last task: advance_checkpoint (only on success of all preceding tasks)
    """
    raise NotImplementedError(
        "Planned production DAG: incremental scheduling requires live checkpoints, "
        "Airflow, and cloud storage wiring."
    )


# dag = build_incremental_dag()
