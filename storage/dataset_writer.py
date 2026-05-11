"""Parquet writes to GCS, partitioned for downstream BigQuery external tables.

Partitioning convention:
  gs://{bucket}/{layer}/{table}/chain_id={chain}/block_date={YYYY-MM-DD}/
  run_partition_id={id}/{file}.parquet

Every write is tagged with `run_partition_id` (lineage column on every row),
but the parquet path itself uses `run_partition_id` as a directory so replays
are isolatable for safe deletes.

Implementation note: when `gcs_path` starts with `gs://`, we use the
`google.cloud.storage` client. Otherwise we treat it as a local path (handy
for unit tests and the `repro.sh --fixture-only` path).

We import `google.cloud.storage` lazily so unit tests don't need GCP creds.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from decoder.types import (
    Block,
    DecodedCall,
    DecodedEvent,
    DecodeResult,
    RawLog,
    RawTrace,
    Receipt,
    TokenBalance,
    Transaction,
    WriteResult,
)


def _to_dict(item: Any) -> dict[str, Any]:
    if is_dataclass(item) and not isinstance(item, type):
        return asdict(item)
    if hasattr(item, "_asdict"):
        return dict(item._asdict())
    if isinstance(item, dict):
        return item
    raise TypeError(f"can't serialize {type(item).__name__}")


def _write_local(rows: list[dict[str, Any]], local_path: Path) -> int:
    """Write rows as JSON-lines (one record per line). Returns bytes
    written. Local fallback used for unit tests; production wires this to
    parquet via pyarrow.

    The parquet path is exposed via `_write_parquet_to_gcs` below; both are
    callable from the same writer functions.
    """
    local_path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(r, default=str, separators=(",", ":")) for r in rows)
    local_path.write_text(payload)
    return local_path.stat().st_size


def _write_parquet_to_gcs(
    rows: list[dict[str, Any]], gcs_path: str, run_partition_id: str
) -> tuple[int, int]:
    """Convert rows → pyarrow Table → parquet bytes, upload to GCS. Returns
    (rows_written, bytes_written)."""
    if not gcs_path.startswith("gs://"):
        # local fallback
        local_path = Path(gcs_path) / f"part-{run_partition_id}.jsonl"
        return len(rows), _write_local(rows, local_path)

    import io

    from google.cloud import storage  # type: ignore[import-untyped]

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(f"pyarrow required for parquet writes: {exc}") from exc

    if not rows:
        # Skip empty partitions; record zero bytes
        return 0, 0

    table = pa.Table.from_pylist(rows)
    buf = io.BytesIO()
    pq.write_table(table, buf)
    data_bytes = buf.getvalue()

    # Parse gs:// URL
    without_scheme = gcs_path[len("gs://") :]
    bucket_name, _, object_prefix = without_scheme.partition("/")
    object_name = (
        f"{object_prefix.rstrip('/')}/part-{run_partition_id}.parquet"
        if object_prefix
        else f"part-{run_partition_id}.parquet"
    )

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    blob.upload_from_string(data_bytes, content_type="application/octet-stream")
    return len(rows), len(data_bytes)


def _write(items: Iterable[Any], gcs_path: str, run_partition_id: str) -> WriteResult:
    """Common writer: dump dataclasses → list[dict] with run_partition_id
    appended → upload (parquet) or write JSON-lines (local fallback).
    """
    rows = []
    for item in items:
        d = _to_dict(item)
        d["run_partition_id"] = run_partition_id
        d["ingested_at"] = int(time.time())
        rows.append(d)
    n_rows, n_bytes = _write_parquet_to_gcs(rows, gcs_path, run_partition_id)
    return WriteResult(
        gcs_path=gcs_path,
        rows=n_rows,
        bytes_written=n_bytes,
        run_partition_id=run_partition_id,
    )


def write_blocks_parquet(
    blocks: Iterable[Block], gcs_path: str, run_partition_id: str
) -> WriteResult:
    return _write(blocks, gcs_path, run_partition_id)


def write_transactions_parquet(
    txs: Iterable[Transaction], gcs_path: str, run_partition_id: str
) -> WriteResult:
    return _write(txs, gcs_path, run_partition_id)


def write_receipts_parquet(
    receipts: Iterable[Receipt], gcs_path: str, run_partition_id: str
) -> WriteResult:
    return _write(receipts, gcs_path, run_partition_id)


def write_logs_parquet(logs: Iterable[RawLog], gcs_path: str, run_partition_id: str) -> WriteResult:
    return _write(logs, gcs_path, run_partition_id)


def write_traces_parquet(
    traces: Iterable[RawTrace], gcs_path: str, run_partition_id: str
) -> WriteResult:
    return _write(traces, gcs_path, run_partition_id)


def write_balance_snapshots_parquet(
    snapshots: Iterable[TokenBalance], gcs_path: str, run_partition_id: str
) -> WriteResult:
    return _write(snapshots, gcs_path, run_partition_id)


def write_decoded_events_parquet(
    events: Iterable[DecodedEvent], gcs_path: str, run_partition_id: str
) -> WriteResult:
    return _write(events, gcs_path, run_partition_id)


def write_decoded_trace_calls_parquet(
    calls: Iterable[DecodedCall], gcs_path: str, run_partition_id: str
) -> WriteResult:
    return _write(calls, gcs_path, run_partition_id)


def write_decode_failures_parquet(
    failures: Iterable[DecodeResult], gcs_path: str, run_partition_id: str
) -> WriteResult:
    """Persist every failed DecodeResult so dbt's `int_decode_failures` and
    the unknown-signature monitor can detect ABI drift and unregistered
    contracts."""
    return _write(failures, gcs_path, run_partition_id)
