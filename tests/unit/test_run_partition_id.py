"""Tests for `lineage.run_metadata.compute_run_partition_id` (idempotency
grain 7)."""

from __future__ import annotations

import hashlib

import pytest

from lineage.run_metadata import compute_run_partition_id


def test_compute_run_partition_id_deterministic() -> None:
    args = (1, "staking_pipeline", "run_001", "logs", "2026-05-10")
    assert compute_run_partition_id(*args) == compute_run_partition_id(*args)


def test_compute_run_partition_id_distinct_per_chain() -> None:
    a = compute_run_partition_id(1, "dag", "run", "src", "p")
    b = compute_run_partition_id(2, "dag", "run", "src", "p")
    assert a != b


def test_compute_run_partition_id_distinct_per_run() -> None:
    a = compute_run_partition_id(1, "dag", "run_a", "src", "p")
    b = compute_run_partition_id(1, "dag", "run_b", "src", "p")
    assert a != b


def test_compute_run_partition_id_64_char_hex() -> None:
    rid = compute_run_partition_id(1, "dag", "run", "src", "p")
    assert len(rid) == 64
    int(rid, 16)


def test_compute_run_partition_id_pure_sha256() -> None:
    canonical = "run_partition|1|dag|run|src|p"
    expected = hashlib.sha256(canonical.encode()).hexdigest()
    assert compute_run_partition_id(1, "dag", "run", "src", "p") == expected


@pytest.mark.parametrize(
    "args",
    [
        (1, "d", "r", "s", "p"),
        (2, "d", "r", "s", "p"),
        (1, "d2", "r", "s", "p"),
        (1, "d", "r2", "s", "p"),
        (1, "d", "r", "s2", "p"),
        (1, "d", "r", "s", "p2"),
    ],
)
def test_compute_run_partition_id_changes_per_input(args: tuple) -> None:
    """Each component varying produces a unique id."""
    base = compute_run_partition_id(1, "d", "r", "s", "p")
    rid = compute_run_partition_id(*args)
    if args == (1, "d", "r", "s", "p"):
        assert rid == base
    else:
        assert rid != base
