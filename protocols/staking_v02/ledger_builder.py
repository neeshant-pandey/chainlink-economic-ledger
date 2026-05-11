"""Double-entry ledger construction.

Every economic action produces zero or more LedgerEntry rows. Per-tx invariant
:

    sum(entry.amount_link * direction_sign(entry.direction)) == 0

That invariant is enforced by `verify_double_entry` and tested in:
  - tests/unit/test_ledger_builder.py
  - dbt/tests/assert_ledger_balanced_per_tx.sql

If a new action kind violates this, the action's `build_ledger_entries` is
wrong — fix the builder, don't loosen the test.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from protocols.staking_v02.semantics import ActionKind, EconomicAction
from reconciliation.movement_builder import TokenMovement


class Direction(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: str  # idempotency grain 6
    action_id: str
    entry_index: int  # 0-based within an action; deterministic
    account: str  # wallet address OR pool role (e.g. "community_pool:rewards")
    direction: Direction
    amount_link: int  # always positive; sign comes from `direction`
    chain_id: int
    block_number: int
    tx_hash: str


@dataclass(frozen=True)
class DoubleEntryCheck:
    tx_hash: str
    is_balanced: bool
    debit_total: int
    credit_total: int
    delta: int  # debit - credit; 0 when balanced


def compute_ledger_entry_id(action_id: str, entry_index: int) -> str:
    """SHA-256 of `(action_id, entry_index)`. Two replays of the same action
    produce identical IDs.
    """
    canonical = f"ledger_entry|{action_id}|{entry_index}"
    return hashlib.sha256(canonical.encode()).hexdigest()


def _make_entry(
    action: EconomicAction,
    entry_index: int,
    account: str,
    direction: Direction,
    amount: int,
) -> LedgerEntry:
    return LedgerEntry(
        entry_id=compute_ledger_entry_id(action.action_id, entry_index),
        action_id=action.action_id,
        entry_index=entry_index,
        account=account,
        direction=direction,
        amount_link=amount,
        chain_id=action.chain_id,
        block_number=action.block_number,
        tx_hash=action.tx_hash,
    )


def build_ledger_entries(
    action: EconomicAction,
    movements: list[TokenMovement],
) -> list[LedgerEntry]:
    """Produces the canonical entry pair(s) for an action, using token
    movements as evidence for the `from`/`to` accounts.

    Examples (all balanced — debits == credits):
      stake(amount=100): [debit wallet 100, credit pool 100]
      reward_claimed(amount=5):  [debit pool:rewards 5, credit wallet 5]
      slashed(amount=10): [debit pool 10, credit pool:forfeiture_sink 10]
      migrated_from_v01(amount=50): [debit pool_v01 50, credit pool_v02 50]

    Edge case: an action with `amount_link == 0` (admin event) emits zero
    entries (no LINK changes hands). The reconciliation layer marks it
    NOT_EXPECTED so this is consistent.
    """
    if action.amount_link == 0:
        return []

    pool_account = f"{action.pool_role}:{action.contract_address}"
    wallet_account = f"wallet:{action.wallet or 'unknown'}"
    amount = action.amount_link

    if action.kind == ActionKind.STAKE:
        # debit wallet, credit pool
        return [
            _make_entry(action, 0, wallet_account, Direction.DEBIT, amount),
            _make_entry(action, 1, pool_account, Direction.CREDIT, amount),
        ]
    if action.kind == ActionKind.UNSTAKE_FINALIZED:
        # debit pool, credit wallet
        return [
            _make_entry(action, 0, pool_account, Direction.DEBIT, amount),
            _make_entry(action, 1, wallet_account, Direction.CREDIT, amount),
        ]
    if action.kind == ActionKind.REWARD_CLAIMED:
        rewards_account = f"{action.pool_role}:rewards"
        return [
            _make_entry(action, 0, rewards_account, Direction.DEBIT, amount),
            _make_entry(action, 1, wallet_account, Direction.CREDIT, amount),
        ]
    if action.kind == ActionKind.REWARD_ACCRUED:
        # off-token; debit external "reward_funder", credit "rewards" pool
        rewards_account = f"{action.pool_role}:rewards"
        return [
            _make_entry(action, 0, "reward_funder", Direction.DEBIT, amount),
            _make_entry(action, 1, rewards_account, Direction.CREDIT, amount),
        ]
    if action.kind == ActionKind.SLASHED:
        forfeiture_account = f"{action.pool_role}:forfeiture_sink"
        return [
            _make_entry(action, 0, pool_account, Direction.DEBIT, amount),
            _make_entry(action, 1, forfeiture_account, Direction.CREDIT, amount),
        ]
    if action.kind == ActionKind.MIGRATED_FROM_V01:
        # The semantics layer has already split this into TWO actions
        # (one with pool_role='staking_pool_v01', one with 'staking_pool_v02').
        # Each individual action contributes a balanced pair: the v01 side
        # credits the wallet (wallet receives v01 burn proceeds, conceptually)
        # while v02 debits and the wallet credits the v02 pool. To keep both
        # actions balanced individually, we model migration as a single
        # transfer-like flow: v01 debit, v02 credit, wallet net zero.
        if action.pool_role == "staking_pool_v01":
            v01_account = f"staking_pool_v01:{action.contract_address}"
            return [
                _make_entry(action, 0, v01_account, Direction.DEBIT, amount),
                _make_entry(action, 1, "migration_proxy", Direction.CREDIT, amount),
            ]
        # v02 side
        return [
            _make_entry(action, 0, "migration_proxy", Direction.DEBIT, amount),
            _make_entry(action, 1, pool_account, Direction.CREDIT, amount),
        ]
    if action.kind == ActionKind.UNSTAKE_REQUESTED:
        # No token movement — but to keep the ledger complete we record a
        # zero-amount marker pair OR no entries. Per the spec, this kind has
        # no expected movement (NOT_EXPECTED) and contributes no ledger rows.
        return []
    if action.kind == ActionKind.POOL_CONFIG_CHANGED:
        return []

    # Movements are accepted but currently informational — used by callers to
    # cross-check; not used to decide the entry shape.
    _ = movements
    return []


def verify_double_entry(entries: list[LedgerEntry]) -> DoubleEntryCheck:
    """Per-tx invariant check. Caller groups by `tx_hash` first.

    If the input contains entries from multiple txs, this function uses the
    tx_hash of the first entry for the result and asserts on the SUM of all
    debits/credits across all entries. For a true per-tx report, group first.
    """
    if not entries:
        return DoubleEntryCheck(
            tx_hash="", is_balanced=True, debit_total=0, credit_total=0, delta=0
        )

    debit_total = sum(e.amount_link for e in entries if e.direction == Direction.DEBIT)
    credit_total = sum(e.amount_link for e in entries if e.direction == Direction.CREDIT)
    delta = debit_total - credit_total
    return DoubleEntryCheck(
        tx_hash=entries[0].tx_hash,
        is_balanced=(delta == 0),
        debit_total=debit_total,
        credit_total=credit_total,
        delta=delta,
    )


def verify_double_entry_per_tx(entries: list[LedgerEntry]) -> list[DoubleEntryCheck]:
    """Group entries by tx_hash and emit a DoubleEntryCheck per tx."""
    by_tx: dict[str, list[LedgerEntry]] = {}
    for e in entries:
        by_tx.setdefault(e.tx_hash, []).append(e)
    return [verify_double_entry(group) for group in by_tx.values()]
