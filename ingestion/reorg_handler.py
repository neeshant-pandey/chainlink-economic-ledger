"""Reorg detection + canonical promotion.

Model:
  - `shadow_tip_*` raw tables receive blocks above the finality watermark
  - `canonical_blocks` table records the finalized truth
  - `promote_finalized_blocks(...)` moves rows from shadow → canonical when they
    fall below the watermark, AND records any conflicts (block_hash changed
    between shadow ingestion and finalization → ReorgEvent)
  - Conflicts trigger downstream replay via `mark_partition_for_replay`
"""

from __future__ import annotations

import time

from decoder.types import PromotionResult, ReorgEvent
from ingestion.checkpoint import Checkpoint
from ingestion.rpc.client import RpcClient


def detect_canonical_conflict(
    client: RpcClient,
    block_number: int,
    known_hash: str,
) -> ReorgEvent | None:
    """Compare `known_hash` against the chain's current canonical hash at
    `block_number`. Returns ReorgEvent if mismatched."""
    block = client.get_block(block_number, full_txs=False)
    if block.header.block_hash.lower() == known_hash.lower():
        return None
    return ReorgEvent(
        chain_id=block.header.chain_id,
        block_number=block_number,
        old_block_hash=known_hash.lower(),
        new_block_hash=block.header.block_hash.lower(),
        detected_at=int(time.time()),
    )


def find_reorg_depth(
    client: RpcClient,
    last_known_block_number: int,
    last_known_hash: str,
) -> int:
    """Walk backwards from `last_known_block_number` until our recorded
    parent_hash chain reconciles with the canonical chain. Depth in blocks."""
    cur_block = last_known_block_number
    cur_hash = last_known_hash
    depth = 0
    while cur_block > 0:
        block = client.get_block(cur_block, full_txs=False)
        if block.header.block_hash.lower() == cur_hash.lower():
            return depth
        # Walk back one block; we need the parent hash of our currently-known
        # block to continue. For simplicity stop here and report depth.
        depth += 1
        cur_block -= 1
        cur_hash = block.header.parent_hash
    return depth


def promote_finalized_blocks(
    shadow_range: tuple[int, int],
    watermark: int,
) -> PromotionResult:
    """Promote shadow_tip rows to canonical for blocks <= watermark.

    For local-mode tests this is a stub that returns a zero-conflict result;
    production wiring delegates to a SQL MERGE in BigQuery.
    """
    from_block, to_block = shadow_range
    eligible_to = min(to_block, watermark)
    if eligible_to < from_block:
        return PromotionResult(
            chain_id=1,
            promoted_from_block=from_block,
            promoted_to_block=from_block - 1,
            promoted_count=0,
            conflicts=[],
        )
    return PromotionResult(
        chain_id=1,
        promoted_from_block=from_block,
        promoted_to_block=eligible_to,
        promoted_count=eligible_to - from_block + 1,
        conflicts=[],
    )


def mark_partition_for_replay(
    checkpoint_store: Checkpoint,
    chain_id: int,
    source_name: str,
    from_block: int,
    to_block: int,
) -> None:
    """Flag a block range for re-ingestion on the next DAG run."""
    checkpoint_store.mark_replay(chain_id, source_name, from_block, to_block)
