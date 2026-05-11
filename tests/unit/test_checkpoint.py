"""Tests for `ingestion.checkpoint`."""

from __future__ import annotations

from pathlib import Path

import pytest

from ingestion.checkpoint import (
    Checkpoint,
    get_last_processed_block,
    set_last_processed_block,
)


@pytest.fixture(autouse=True)
def _redirect_checkpoint_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHECKPOINT_DIR", str(tmp_path))


def test_get_set_last_processed_block_roundtrip() -> None:
    set_last_processed_block(1, "test_dag", 1000, "rpid-A")
    assert get_last_processed_block(1, "test_dag") == 1000


def test_get_last_processed_block_returns_none_initially() -> None:
    assert get_last_processed_block(1, "never_run") is None


def test_set_last_processed_block_overwrites() -> None:
    set_last_processed_block(1, "dag", 100, "rpid-1")
    set_last_processed_block(1, "dag", 200, "rpid-2")
    assert get_last_processed_block(1, "dag") == 200


def test_advance_idempotent_for_lower_block(tmp_path: Path) -> None:
    cp = Checkpoint(tmp_path / "cp.json")
    cp.advance(1, "src", 100, "0xhash100")
    cp.advance(1, "src", 50, "0xhash50")
    assert cp.last_processed_block(1, "src") == 100


def test_advance_records_block_hash(tmp_path: Path) -> None:
    cp = Checkpoint(tmp_path / "cp.json")
    cp.advance(1, "src", 100, "0xabc")
    assert cp.last_processed_block_hash(1, "src") == "0xabc"


def test_mark_replay_then_pending_replays(tmp_path: Path) -> None:
    cp = Checkpoint(tmp_path / "cp.json")
    cp.mark_replay(1, "src", 100, 200)
    assert (100, 200) in cp.pending_replays(1, "src")


def test_clear_replay_drains_range(tmp_path: Path) -> None:
    cp = Checkpoint(tmp_path / "cp.json")
    cp.mark_replay(1, "src", 100, 200)
    cp.clear_replay(1, "src", 100, 200)
    assert cp.pending_replays(1, "src") == []
