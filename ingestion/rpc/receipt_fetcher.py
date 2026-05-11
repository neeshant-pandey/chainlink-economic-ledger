"""Transaction receipts. Required for:
- `status` (filter reverted txs from movement extraction)
- `gas_used` / `effective_gas_price` (gas economics in marts)
- `logs_count` (sanity vs `raw_logs`)
"""

from __future__ import annotations

from decoder.types import Receipt
from ingestion.rpc.client import RpcClient


def fetch_receipts_for_block(client: RpcClient, block_number: int) -> list[Receipt]:
    """All receipts for the block. Order matches `tx_index`. Delegates to the
    client's batched receipts API by first listing the block's tx hashes."""
    block = client.get_block(block_number, full_txs=False)
    return fetch_receipts_for_txs(client, list(block.transaction_hashes))


def fetch_receipts_for_txs(
    client: RpcClient,
    tx_hashes: list[str],
    batch_size: int = 50,
) -> list[Receipt]:
    """Batched receipt fetch. Order of return matches input order."""
    out: list[Receipt] = []
    for i in range(0, len(tx_hashes), batch_size):
        chunk = tx_hashes[i : i + batch_size]
        out.extend(client.get_receipts_batch(chunk))
    return out
