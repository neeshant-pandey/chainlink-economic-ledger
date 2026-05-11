"""Tests for `ingestion.finality`."""

from __future__ import annotations

from pathlib import Path

from ingestion.finality import (
    DEFAULT_FINALITY_DEPTH,
    compute_finality_watermark,
    compute_safe_to_block,
    is_block_finalized,
    load_finality_window_blocks,
    watermark_from_settings,
)


class _RpcStub:
    def __init__(self, finalized: int = 0, raise_on_finalized: bool = False) -> None:
        self._finalized = finalized
        self._raise = raise_on_finalized

    def get_finalized_block_number(self) -> int:
        if self._raise:
            raise RuntimeError("not supported")
        return self._finalized

    def get_chain_id(self) -> int:
        return 1


def test_compute_finality_watermark_uses_finalized_tag() -> None:
    """When the chain reports a finalized block, the watermark equals it."""
    client = _RpcStub(finalized=18_000_000)
    assert compute_finality_watermark(client, finality_depth=64) == 18_000_000


def test_compute_finality_watermark_falls_back_to_depth() -> None:
    client = _RpcStub(raise_on_finalized=True)
    # When client raises, we fall back to a non-zero watermark = depth
    assert compute_finality_watermark(client, finality_depth=64) == 64


def test_is_block_finalized_boundary() -> None:
    assert is_block_finalized(100, 100) is True
    assert is_block_finalized(101, 100) is False
    assert is_block_finalized(99, 100) is True


def test_compute_safe_to_block_never_exceeds_watermark() -> None:
    client = _RpcStub(finalized=18_000_000)
    assert compute_safe_to_block(client) == compute_finality_watermark(client)


def test_load_finality_window_blocks_default(tmp_path: Path) -> None:
    """When config is missing, returns the default."""
    missing = tmp_path / "missing.yaml"
    assert load_finality_window_blocks(missing) == DEFAULT_FINALITY_DEPTH


def test_load_finality_window_blocks_reads_yaml(tmp_path: Path) -> None:
    cfg = tmp_path / "settings.yaml"
    cfg.write_text("ingestion:\n  finality_window_blocks: 128\n")
    assert load_finality_window_blocks(cfg) == 128


def test_watermark_from_settings(tmp_path: Path) -> None:
    cfg = tmp_path / "settings.yaml"
    cfg.write_text("ingestion:\n  finality_window_blocks: 200\n")
    assert watermark_from_settings(cfg) == 200
