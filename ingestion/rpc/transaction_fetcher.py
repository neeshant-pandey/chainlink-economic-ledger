"""Transaction ingestion. Used for calldata decoding (entry-point methods on the
staking pool) and to populate `raw_transactions`."""

from __future__ import annotations

from decoder.types import Transaction
from ingestion.rpc.client import RpcClient


def fetch_transactions_for_block(client: RpcClient, block_number: int) -> list[Transaction]:
    """All transactions in the block. Order matches `tx_index`."""
    block = client.get_block(block_number, full_txs=True)
    return list(block.full_transactions or [])


def fetch_transactions_batch(client: RpcClient, tx_hashes: list[str]) -> list[Transaction]:
    """Sequential — the underlying client may not support batched
    eth_getTransactionByHash. Order matches input order."""
    return [client.get_transaction(h) for h in tx_hashes]  # type: ignore[attr-defined]
