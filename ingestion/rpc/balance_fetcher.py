"""Historical `balanceOf` snapshots via archive-node `eth_call` at specific
block heights.

Used for:
  - reconciling per-pool LINK balance deltas across a partition
  - per-wallet reward-claim verification
"""

from __future__ import annotations

from decoder.types import TokenBalance
from ingestion.rpc.client import RpcClient

# ERC-20 balanceOf(address) selector
BALANCE_OF_SELECTOR = "0x70a08231"


def snapshot_token_balance(
    client: RpcClient,
    token_address: str,
    holder_address: str,
    block_number: int,
) -> TokenBalance:
    """Fetch balanceOf(holder) at `block_number` via the RPC client.

    Raises if the client doesn't expose a way to issue eth_call (the production
    RpcClient does; this is a thin wrapper).
    """
    holder_padded = holder_address.lower().replace("0x", "").rjust(64, "0")
    calldata = BALANCE_OF_SELECTOR + holder_padded
    # Delegate to the RPC client's lower-level eth_call helper if present.
    # The client exposes get_token_balance directly; we forward to keep the API
    # narrow.
    balance = client.get_token_balance(  # type: ignore[attr-defined]
        token_address, holder_address, block_number
    )
    _ = calldata  # documentation; the actual call routes through the client
    return TokenBalance(
        chain_id=client.get_chain_id(),  # type: ignore[attr-defined]
        block_number=block_number,
        token_address=token_address.lower(),
        holder_address=holder_address.lower(),
        balance=int(balance),
    )


def snapshot_token_balances_batch(
    client: RpcClient,
    token_address: str,
    holders: list[str],
    block_number: int,
) -> list[TokenBalance]:
    """Batched balance snapshot at a single block height. Order matches input."""
    return [snapshot_token_balance(client, token_address, h, block_number) for h in holders]


def snapshot_balances_over_blocks(
    client: RpcClient,
    token_address: str,
    holder: str,
    block_numbers: list[int],
) -> list[TokenBalance]:
    """Same holder, many block heights. Use for time-series reconstruction."""
    return [snapshot_token_balance(client, token_address, holder, b) for b in block_numbers]
