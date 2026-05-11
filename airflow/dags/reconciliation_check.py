"""Daily reconciliation report DAG.

Runs the partition-level reconciliation, all data-quality checks
(`reconciliation/checks.py`), and the Databricks parity check
(`databricks/notebooks/parity_check.py`). Emits metrics + alerts.

This DAG is the single source of truth for "is the data healthy today?"
"""

from __future__ import annotations

# ruff: noqa


def build_reconciliation_dag():
    """Implementation contract:
    - DAG id: 'reconciliation_check'
    - Schedule: '0 6 * * *'  (06:00 UTC daily)
    - Catchup: False
    - Tasks:
        1. reconcile_partition (last 7 days)
        2. all checks in reconciliation/checks.py
        3. databricks parity_check
        4. emit metrics
        5. emit alerts (only failed CheckResults)
    - Critical-severity check failures fail the DAG (paging policy in runbook).
      Warn-severity failures alert but pass the DAG.
    """
    raise NotImplementedError(
        "Planned production DAG: the local fixture demo runs reconciliation directly "
        "through Python and dbt tests without an Airflow scheduler."
    )


# dag = build_reconciliation_dag()
