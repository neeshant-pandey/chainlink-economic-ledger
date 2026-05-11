"""Block + block-header ingestion.

Block headers are written for every fetched block (canonical AND shadow tip) so the
reorg handler has a complete record to reconcile against.
"""

from __future__ import annotations

from decoder.types import Block, BlockHeader
from ingestion.rpc.client import RpcClient


def fetch_block_range(
    client: RpcClient,
    from_block: int,
    to_block: int,
    full_txs: bool = False,
) -> list[Block]:
    """Inclusive range. Sequential — caller is expected to parallelize with
    a thread pool if needed. Order of return is ascending by block_number."""
    return [client.get_block(b, full_txs=full_txs) for b in range(from_block, to_block + 1)]


def fetch_canonical_block_headers(
    client: RpcClient,
    from_block: int,
    to_block: int,
) -> list[BlockHeader]:
    """Lightweight header-only fetch for canonical_blocks population."""
    return [client.get_block(b, full_txs=False).header for b in range(from_block, to_block + 1)]
