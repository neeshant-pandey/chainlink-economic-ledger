"""Pipeline run metadata.

Every parquet file is tagged with `run_partition_id`. It is recorded as a column
on every row in canonical tables but is NOT part of any mart unique key — marts
merge by stable entity IDs; `run_partition_id` is lineage-only metadata.

`record_run` / `get_run_metadata` use a JSON-on-disk backend so unit tests don't
need a database. Production wiring is in the storage layer.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class RunMetadata:
    run_id: str
    dag_id: str
    chain_id: int
    started_at: int
    completed_at: int | None
    status: Literal["running", "success", "failed"]
    partitions_processed: int
    manifest_ids: list[str]


def compute_run_partition_id(
    chain_id: int,
    dag_id: str,
    run_id: str,
    source_name: str,
    partition_key: str,
) -> str:
    """SHA-256 of `(chain_id, dag_id, run_id, source_name, partition_key)`.

    Two DAG runs producing the same logical partition get distinct
    `run_partition_id`s, so replays are distinguishable in lineage even though
    they overwrite the same canonical rows.
    """
    canonical = f"run_partition|{chain_id}|{dag_id}|{run_id}|{source_name}|{partition_key}"
    return hashlib.sha256(canonical.encode()).hexdigest()


def _metadata_dir() -> Path:
    """Return the directory where run metadata JSON files are written.

    Default: `./.run_metadata` in CWD; override with `RUN_METADATA_DIR` env var.
    """
    base = os.environ.get("RUN_METADATA_DIR", ".run_metadata")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def record_run(
    dag_id: str,
    run_id: str,
    chain_id: int,
    status: Literal["running", "success", "failed"],
    partitions: int,
    manifest_ids: list[str],
    started_at: int = 0,
    completed_at: int | None = None,
) -> RunMetadata:
    """Persist a RunMetadata record to the metadata directory and return it.

    The on-disk format is JSON keyed by run_id. Idempotent: multiple writes
    with the same run_id overwrite the previous file (status transitions are
    expected — `running` → `success` / `failed`).

    Returns the constructed RunMetadata for caller convenience.
    """
    meta = RunMetadata(
        run_id=run_id,
        dag_id=dag_id,
        chain_id=chain_id,
        started_at=started_at,
        completed_at=completed_at,
        status=status,
        partitions_processed=partitions,
        manifest_ids=list(manifest_ids),
    )
    out_path = _metadata_dir() / f"{run_id}.json"
    out_path.write_text(json.dumps(asdict(meta), indent=2))
    return meta


def get_run_metadata(run_id: str) -> RunMetadata:
    """Load a previously-recorded RunMetadata from the metadata directory.

    Raises FileNotFoundError if the run_id was never recorded.
    """
    in_path = _metadata_dir() / f"{run_id}.json"
    if not in_path.exists():
        raise FileNotFoundError(f"run metadata not found for run_id={run_id!r}")
    payload = json.loads(in_path.read_text())
    return RunMetadata(
        run_id=payload["run_id"],
        dag_id=payload["dag_id"],
        chain_id=payload["chain_id"],
        started_at=payload["started_at"],
        completed_at=payload.get("completed_at"),
        status=payload["status"],
        partitions_processed=payload["partitions_processed"],
        manifest_ids=list(payload.get("manifest_ids", [])),
    )
