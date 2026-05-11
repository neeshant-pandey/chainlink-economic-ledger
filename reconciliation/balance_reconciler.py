"""Pool-level balance reconciliation.

Verifies that, for each (pool_address, partition):

    sum(net token movements affecting pool) == balanceOf(pool, end_block) -
                                               balanceOf(pool, start_block)

Mismatches indicate either missing movements (e.g. a transfer mode we didn't
account for) or incorrect classification of a contract as a pool.

We type the RPC client as a `Protocol` (see below) so this module does not
import from `ingestion.rpc.client` at module load time — keeps the dependency
graph one-way (reconciliation does not depend on ingestion's RPC sub-module
implementation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from reconciliation.movement_builder import TokenMovement


class _BalanceProvider(Protocol):
    """Anything that can return an ERC-20 balance at a block. The RPC client
    in `ingestion.rpc.client.RpcClient` matches this implicitly; for unit
    tests, a simple stub class with a matching method works."""

    def get_token_balance(
        self, token_address: str, holder_address: str, block_number: int
    ) -> int: ...


@dataclass(frozen=True)
class BalanceVerification:
    chain_id: int
    pool_address: str
    block_number: int
    expected_delta: int
    observed_balance_delta: int
    is_consistent: bool
    diff: int


@dataclass(frozen=True)
class PoolReconciliation:
    chain_id: int
    pool_address: str
    from_block: int
    to_block: int
    net_movements: int
    start_balance: int
    end_balance: int
    is_consistent: bool
    diff: int


def compute_balance_delta(
    movements: list[TokenMovement],
    address: str,
    from_block: int,
    to_block: int,
) -> int:
    """Net amount of `address` between blocks based on movements only.

    `+amount` for `to_addr=address`, `-amount` for `from_addr=address`. Self-
    transfers (from == to) net to zero. Movements outside [from_block,
    to_block] are ignored.

    Edge case: address comparison is case-insensitive — internal storage
    convention is lowercase but inputs may not be.
    """
    target = address.lower()
    delta = 0
    for m in movements:
        if m.block_number < from_block or m.block_number > to_block:
            continue
        from_lower = m.from_addr.lower()
        to_lower = m.to_addr.lower()
        if to_lower == target:
            delta += m.amount
        if from_lower == target:
            delta -= m.amount
    return delta


def verify_pool_balance(
    client: _BalanceProvider,
    token_address: str,
    pool_address: str,
    block_number: int,
    expected_delta: int,
    prior_block_number: int,
) -> BalanceVerification:
    """Compares `expected_delta` against the on-chain `balanceOf` delta from
    `prior_block_number` to `block_number`.
    """
    prior_balance = client.get_token_balance(token_address, pool_address, prior_block_number)
    current_balance = client.get_token_balance(token_address, pool_address, block_number)
    observed = current_balance - prior_balance
    diff = observed - expected_delta
    return BalanceVerification(
        chain_id=1,
        pool_address=pool_address.lower(),
        block_number=block_number,
        expected_delta=expected_delta,
        observed_balance_delta=observed,
        is_consistent=(diff == 0),
        diff=diff,
    )


def reconcile_pool_movement_vs_balance(
    client: _BalanceProvider,
    token_address: str,
    pool_address: str,
    movements: list[TokenMovement],
    from_block: int,
    to_block: int,
) -> PoolReconciliation:
    """Combine movement-derived delta and on-chain balance delta into a single
    PoolReconciliation record.
    """
    pool_lower = pool_address.lower()
    net_movements = compute_balance_delta(movements, pool_lower, from_block, to_block)

    start_balance = client.get_token_balance(token_address, pool_lower, from_block - 1)
    end_balance = client.get_token_balance(token_address, pool_lower, to_block)
    observed_delta = end_balance - start_balance
    diff = observed_delta - net_movements

    return PoolReconciliation(
        chain_id=1,
        pool_address=pool_lower,
        from_block=from_block,
        to_block=to_block,
        net_movements=net_movements,
        start_balance=start_balance,
        end_balance=end_balance,
        is_consistent=(diff == 0),
        diff=diff,
    )
