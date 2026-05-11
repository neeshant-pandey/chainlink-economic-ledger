"""EvmBalanceSnapshotOperator: pool/wallet balanceOf snapshots at specific blocks.

Used to populate `raw_balance_snapshots` for the balance-reconciliation cross-check.
"""

from __future__ import annotations

# ruff: noqa

from typing import Any


class EvmBalanceSnapshotOperator:
    """Wraps `ingestion.balance_fetcher.snapshot_token_balances_batch`.

    Constructor params:
        chain_id: int
        token_address: str
        holders: list[str] | str       # list, or XCom ref string
        block_number: int              # may be templated
        gcs_bucket: str
        layer: str = "raw_balance_snapshots"
        run_partition_id: str

    Execute returns: GCS manifest path. Pushed to XCom.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            "Planned production operator: balance snapshot execution is not required "
            "for the local fixture demo."
        )

    def execute(self, context: dict[str, Any]) -> str:
        raise NotImplementedError(
            "Planned production operator: wire this to ingestion.rpc.balance_fetcher "
            "and storage.dataset_writer in an Airflow deployment."
        )
