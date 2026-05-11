"""EvmLogExtractOperator: windowed log fetch → parquet → GCS → manifest.

XCom output: GCS manifest path (NOT row data).
"""

from __future__ import annotations

# ruff: noqa  # airflow imports kept symbolic until implementation

from typing import Any


class EvmLogExtractOperator:
    """Wraps `ingestion.log_fetcher.fetch_logs_with_adaptive_window` +
    `storage.dataset_writer.write_logs_parquet` + manifest emission.

    Constructor params:
        chain_id: int
        contract_addresses: list[str]
        topic_filter: list[str | list[str] | None]
        from_block: int          # may be templated via Jinja
        to_block: int            # may be templated via Jinja
        gcs_bucket: str
        layer: str = "raw_logs"
        run_partition_id: str    # passed via XCom from a runtime task

    Execute returns: GCS manifest path (str). Pushed to XCom.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            "Planned production operator: log extraction is exercised locally through "
            "fixture decode scripts, not Airflow."
        )

    def execute(self, context: dict[str, Any]) -> str:
        raise NotImplementedError(
            "Planned production operator: wire this to ingestion.bq/ingestion.rpc "
            "extractors and storage.dataset_writer in an Airflow deployment."
        )
