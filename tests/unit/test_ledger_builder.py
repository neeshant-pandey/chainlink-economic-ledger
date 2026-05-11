"""Tests for `protocols.staking_v02.ledger_builder`. Double-entry invariant
is the contract."""

from __future__ import annotations

import hashlib

from protocols.staking_v02.ledger_builder import (
    Direction,
    LedgerEntry,
    build_ledger_entries,
    compute_ledger_entry_id,
    verify_double_entry,
    verify_double_entry_per_tx,
)
from protocols.staking_v02.semantics import ActionKind, EconomicAction


def _action(
    kind: ActionKind, amount: int = 100, role: str = "community_staking_pool"
) -> EconomicAction:
    return EconomicAction(
        action_id=f"act|{kind.value}|{role}",
        kind=kind,
        chain_id=1,
        block_number=100,
        tx_hash="0xtx",
        log_index=0,
        contract_address="0xpool",
        pool_role=role,
        wallet="0xwallet",
        amount_link=amount,
        source_event_signature="0xsig",
        raw_log_id="rl",
        decoded_event_id="de",
    )


def test_compute_ledger_entry_id_deterministic() -> None:
    a = compute_ledger_entry_id("action_1", 0)
    b = compute_ledger_entry_id("action_1", 0)
    assert a == b
    assert len(a) == 64


def test_compute_ledger_entry_id_pure_sha256() -> None:
    canonical = "ledger_entry|action_1|0"
    assert compute_ledger_entry_id("action_1", 0) == hashlib.sha256(canonical.encode()).hexdigest()


def test_build_ledger_entries_stake_balanced() -> None:
    entries = build_ledger_entries(_action(ActionKind.STAKE, 100), [])
    assert len(entries) == 2
    check = verify_double_entry(entries)
    assert check.is_balanced
    assert check.debit_total == 100 == check.credit_total


def test_build_ledger_entries_reward_claimed_balanced() -> None:
    entries = build_ledger_entries(_action(ActionKind.REWARD_CLAIMED, 50), [])
    assert len(entries) == 2
    assert verify_double_entry(entries).is_balanced


def test_build_ledger_entries_slashed_balanced() -> None:
    entries = build_ledger_entries(_action(ActionKind.SLASHED, 30), [])
    assert len(entries) == 2
    assert verify_double_entry(entries).is_balanced
    # debit pool, credit forfeiture
    accounts = {e.account for e in entries}
    assert any(":forfeiture_sink" in a for a in accounts)


def test_build_ledger_entries_migration_two_pools_balanced() -> None:
    """Both v01-side and v02-side migration actions produce balanced entries."""
    v01 = _action(ActionKind.MIGRATED_FROM_V01, 50, role="staking_pool_v01")
    v02 = _action(ActionKind.MIGRATED_FROM_V01, 50, role="staking_pool_v02")
    e_v01 = build_ledger_entries(v01, [])
    e_v02 = build_ledger_entries(v02, [])
    assert verify_double_entry(e_v01).is_balanced
    assert verify_double_entry(e_v02).is_balanced
    # Combined cross-pool flow nets to zero
    combined = e_v01 + e_v02
    check = verify_double_entry(combined)
    assert check.is_balanced


def test_build_ledger_entries_unstake_requested_no_entries() -> None:
    """UNSTAKE_REQUESTED has no token movement → 0 ledger entries."""
    assert build_ledger_entries(_action(ActionKind.UNSTAKE_REQUESTED, 100), []) == []


def test_build_ledger_entries_zero_amount_edge_case() -> None:
    """Edge case: docstring: 'an action with `amount_link == 0`
    (admin event) emits zero entries (no LINK changes hands)'.

    Exercises EACH kind to confirm the zero-amount gate is the FIRST check,
    not a per-kind gate that drifts.
    """
    for kind in (
        ActionKind.STAKE,
        ActionKind.UNSTAKE_FINALIZED,
        ActionKind.REWARD_CLAIMED,
        ActionKind.REWARD_ACCRUED,
        ActionKind.SLASHED,
        ActionKind.MIGRATED_FROM_V01,
    ):
        entries = build_ledger_entries(_action(kind, amount=0), [])
        assert entries == [], f"{kind} with amount=0 must emit zero entries"


def test_build_ledger_entries_pool_config_changed_emits_no_entries() -> None:
    """POOL_CONFIG_CHANGED is admin-only -> zero entries (no token movement)."""
    assert build_ledger_entries(_action(ActionKind.POOL_CONFIG_CHANGED, 0), []) == []
    # Even with a non-zero amount the kind is admin-only (defensive).
    assert build_ledger_entries(_action(ActionKind.POOL_CONFIG_CHANGED, 100), []) == []


def test_verify_double_entry_balanced() -> None:
    entries = [
        LedgerEntry(
            entry_id="e1",
            action_id="a",
            entry_index=0,
            account="x",
            direction=Direction.DEBIT,
            amount_link=100,
            chain_id=1,
            block_number=1,
            tx_hash="0xtx",
        ),
        LedgerEntry(
            entry_id="e2",
            action_id="a",
            entry_index=1,
            account="y",
            direction=Direction.CREDIT,
            amount_link=100,
            chain_id=1,
            block_number=1,
            tx_hash="0xtx",
        ),
    ]
    check = verify_double_entry(entries)
    assert check.is_balanced
    assert check.delta == 0


def test_verify_double_entry_unbalanced() -> None:
    entries = [
        LedgerEntry(
            entry_id="e1",
            action_id="a",
            entry_index=0,
            account="x",
            direction=Direction.DEBIT,
            amount_link=100,
            chain_id=1,
            block_number=1,
            tx_hash="0xtx",
        ),
        LedgerEntry(
            entry_id="e2",
            action_id="a",
            entry_index=1,
            account="y",
            direction=Direction.CREDIT,
            amount_link=50,  # short
            chain_id=1,
            block_number=1,
            tx_hash="0xtx",
        ),
    ]
    check = verify_double_entry(entries)
    assert check.is_balanced is False
    assert check.delta == 50


def test_verify_double_entry_per_tx_groups() -> None:
    """Returns a check per tx."""
    e1 = LedgerEntry("e1", "a", 0, "x", Direction.DEBIT, 100, 1, 1, "0xtxA")
    e2 = LedgerEntry("e2", "a", 1, "y", Direction.CREDIT, 100, 1, 1, "0xtxA")
    e3 = LedgerEntry("e3", "b", 0, "p", Direction.DEBIT, 50, 1, 2, "0xtxB")
    e4 = LedgerEntry("e4", "b", 1, "q", Direction.CREDIT, 50, 1, 2, "0xtxB")
    checks = verify_double_entry_per_tx([e1, e2, e3, e4])
    assert len(checks) == 2
    assert all(c.is_balanced for c in checks)
