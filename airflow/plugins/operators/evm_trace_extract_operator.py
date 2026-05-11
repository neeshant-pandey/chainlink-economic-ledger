"""EvmTraceExtractOperator: parallel trace fetch → parquet → GCS → manifest.

Tx-list source: an upstream task (typically a SQL or Python task) that selects
the txs needing traces — slashing events, migration events, and txs flagged
'unmatched' by the prior reconciliation run.
"""

from __future__ import annotations

# ruff: noqa

from typing import Any


class EvmTraceExtractOperator:
    """Wraps `ingestion.trace_fetcher.fetch_traces_for_txs` + parquet write.

    Constructor params:
        chain_id: int
        tx_hashes_xcom_key: str    # XCom key carrying list[str] of tx hashes
        gcs_bucket: str
        layer: str = "raw_traces"
        run_partition_id: str
        parallelism: int = 4

    Execute returns: GCS manifest path. Pushed to XCom.

    Fails loudly if `RpcClient.supports_debug_trace()` is False.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            "Planned production operator: trace extraction is exercised locally through "
            "cached fixture traces, not Airflow."
        )

    def execute(self, context: dict[str, Any]) -> str:
        raise NotImplementedError(
            "Planned production operator: wire this to trace extractors and "
            "storage.dataset_writer in an Airflow deployment."
        )
