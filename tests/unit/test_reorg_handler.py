"""Tests for `ingestion.reorg_handler`."""

from __future__ import annotations

from pathlib import Path

from ingestion.checkpoint import Checkpoint
from ingestion.reorg_handler import (
    mark_partition_for_replay,
    promote_finalized_blocks,
)


def test_promote_finalized_blocks_returns_promotion_result_no_conflict() -> None:
    """Range entirely below watermark → fully promoted."""
    result = promote_finalized_blocks(shadow_range=(100, 150), watermark=200)
    assert result.promoted_count == 51
    assert result.promoted_to_block == 150
    assert result.conflicts == []


def test_promote_finalized_blocks_above_watermark_returns_zero() -> None:
    """Range entirely above watermark → nothing to promote."""
    result = promote_finalized_blocks(shadow_range=(300, 400), watermark=200)
    assert result.promoted_count == 0


def test_mark_partition_for_replay_records_range(tmp_path: Path) -> None:
    cp = Checkpoint(tmp_path / "cp.json")
    mark_partition_for_replay(cp, 1, "src", 100, 200)
    assert (100, 200) in cp.pending_replays(1, "src")
