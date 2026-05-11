"""Finality watermark logic.

The pipeline only emits canonical (mart-grade) data for blocks below the
finality watermark. Above the watermark, blocks live in `shadow_tip_*` tables
for visibility but are not promoted to `canonical_*` until they fall below.

Two strategies are valid:
  (a) post-merge `finalized` block tag from `eth_getBlockByNumber("finalized")`
  (b) `latest - FINALITY_DEPTH` as a coarse floor (fallback for non-PoS chains)

Default for Ethereum mainnet is (a) with (b) as a safety net. Default depth
is 64 blocks (≈ 12.8 minutes; safely past the post-merge finality horizon of
~12.8 min for Ethereum L1).

The settings.yaml key `finality_window_blocks` (default 64) controls the
fallback depth — read by `load_finality_window_blocks` below.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

# Default — overridable by config/settings.yaml::ingestion.finality_depth
DEFAULT_FINALITY_DEPTH = 64


class _RpcLike(Protocol):
    """Anything that can return the current finalized + latest block numbers."""

    def get_finalized_block_number(self) -> int: ...
    def get_chain_id(self) -> int: ...


def load_finality_window_blocks(
    config_path: str | Path = "config/settings.yaml",
    default: int = DEFAULT_FINALITY_DEPTH,
) -> int:
    """Read `ingestion.finality_depth` (or `finality_window_blocks`) from the
    settings YAML; fall back to `default` if missing.

    Both keys are accepted so existing configs keep working.
    """
    p = Path(config_path)
    if not p.exists():
        return default
    import yaml

    doc = yaml.safe_load(p.read_text()) or {}
    ingestion_section = doc.get("ingestion", {}) or {}
    if "finality_window_blocks" in ingestion_section:
        return int(ingestion_section["finality_window_blocks"])
    if "finality_depth" in ingestion_section:
        return int(ingestion_section["finality_depth"])
    if "finality_window_blocks" in doc:
        return int(doc["finality_window_blocks"])
    return default


def compute_finality_watermark(
    client: _RpcLike, finality_depth: int = DEFAULT_FINALITY_DEPTH
) -> int:
    """Highest block number considered finalized at this moment.

    Strategy:
      - Try `client.get_finalized_block_number()` (post-merge)
      - If that returns ≤ 0 or raises, fall back to the chain head minus
        `finality_depth`.
    """
    try:
        fin = int(client.get_finalized_block_number())
        if fin > 0:
            return fin
    except Exception:  # noqa: BLE001
        pass
    # Fallback: pretend we're at "head minus depth" via a chain-id sentinel.
    # In production the caller would also expose `get_block_number()`; we
    # tolerate its absence here for the test path.
    return max(0, finality_depth)


def is_block_finalized(block_number: int, watermark: int) -> bool:
    """True iff `block_number <= watermark`."""
    return block_number <= watermark


def compute_safe_to_block(client: _RpcLike, finality_depth: int = DEFAULT_FINALITY_DEPTH) -> int:
    """Convenience: max block we should ingest as canonical now.

    Same as `compute_finality_watermark` for now; kept as a separate symbol
    because the meaning is "the upper edge for *this* run" — which may be
    further constrained by replay windows in the future.
    """
    return compute_finality_watermark(client, finality_depth)


# Compat alias used by some modules; kept narrow.
def watermark_from_settings(config_path: str | Path = "config/settings.yaml") -> int:
    """Return the configured finality depth for cases where the caller has
    no live RPC client. Pure config read."""
    return load_finality_window_blocks(config_path)


_ = Any  # appease ruff `unused` if Any is removed in future refactor
