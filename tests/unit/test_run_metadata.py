"""public-function coverage for `lineage/run_metadata.py`.

Exercises every public function:
  - compute_run_partition_id (also covered by L5 property tests)
  - record_run
  - get_run_metadata

Plus the round-trip invariant: record + get returns the same RunMetadata.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from lineage.run_metadata import (
    RunMetadata,
    compute_run_partition_id,
    get_run_metadata,
    record_run,
)


def test_compute_run_partition_id_deterministic() -> None:
    """Same inputs -> same id; pure function."""
    a = compute_run_partition_id(1, "dag", "run1", "src", "2026-05-11")
    b = compute_run_partition_id(1, "dag", "run1", "src", "2026-05-11")
    assert isinstance(a, str)
    assert a == b
    assert len(a) == 64


def test_compute_run_partition_id_is_sha256_of_canonical_key() -> None:
    """Public contract: id == sha256(canonical) where canonical is documented."""
    expected = hashlib.sha256(b"run_partition|1|dag|run1|src|2026-05-11").hexdigest()
    assert compute_run_partition_id(1, "dag", "run1", "src", "2026-05-11") == expected


def test_compute_run_partition_id_distinguishes_run_ids() -> None:
    """Different run_id -> different partition_id (so replays don't collide)."""
    a = compute_run_partition_id(1, "dag", "run_alpha", "src", "p")
    b = compute_run_partition_id(1, "dag", "run_beta", "src", "p")
    assert a != b


def test_record_run_persists_and_roundtrips(tmp_path: Path) -> None:
    """record_run writes JSON; get_run_metadata reads it back identically."""
    os.environ["RUN_METADATA_DIR"] = str(tmp_path)
    try:
        rec = record_run(
            dag_id="staking_pipeline",
            run_id="r-001",
            chain_id=1,
            status="success",
            partitions=3,
            manifest_ids=["m1", "m2"],
            started_at=1700000000,
            completed_at=1700000100,
        )
        assert isinstance(rec, RunMetadata)
        # Round-trip
        loaded = get_run_metadata("r-001")
        assert loaded.run_id == "r-001"
        assert loaded.dag_id == "staking_pipeline"
        assert loaded.chain_id == 1
        assert loaded.status == "success"
        assert loaded.partitions_processed == 3
        assert loaded.manifest_ids == ["m1", "m2"]
        assert loaded.started_at == 1700000000
        assert loaded.completed_at == 1700000100
    finally:
        os.environ.pop("RUN_METADATA_DIR", None)


def test_get_run_metadata_raises_when_missing(tmp_path: Path) -> None:
    """A run_id that was never recorded -> FileNotFoundError per docstring."""
    os.environ["RUN_METADATA_DIR"] = str(tmp_path)
    try:
        with pytest.raises(FileNotFoundError):
            get_run_metadata("nonexistent-run-id")
    finally:
        os.environ.pop("RUN_METADATA_DIR", None)


def test_record_run_idempotent_overwrite(tmp_path: Path) -> None:
    """Same run_id written twice -> second write overwrites (status transitions
    are expected per docstring)."""
    os.environ["RUN_METADATA_DIR"] = str(tmp_path)
    try:
        record_run("dag", "r-2", 1, "running", 0, [])
        first = get_run_metadata("r-2")
        assert first.status == "running"

        record_run("dag", "r-2", 1, "success", 5, ["m1"])
        second = get_run_metadata("r-2")
        assert second.status == "success"
        assert second.partitions_processed == 5
    finally:
        os.environ.pop("RUN_METADATA_DIR", None)
