"""public-function coverage for `protocols/payment_abstraction/ledger_builder.py`.

Exercises every PAActionKind branch of `build_pa_ledger_entries` and confirms
each is balanced via `verify_pa_double_entry`. Also exercises
`compute_pa_ledger_entry_id` determinism.
"""

from __future__ import annotations

import hashlib

from protocols.payment_abstraction.ledger_builder import (
    PALedgerEntry,
    build_pa_ledger_entries,
    compute_pa_ledger_entry_id,
    verify_pa_double_entry,
)
from protocols.payment_abstraction.semantics import (
    PAActionKind,
    PAEconomicAction,
)

LINK = "0x514910771af9ca656af840dff83e8264ecf986ca"
PA_RESERVES = "0x5680681ed3767b96914ce741a308155c7fb9171d"
PA_FEE_AGGREGATOR = "0xd6e39d42acee7abcc460e6ea78a0844a0980e78f"
PA_SWAP = "0x36e827ba2b270535ca1b099a6ba2b280ddc0315e"


def _action(
    kind: PAActionKind,
    contract_address: str,
    contract_role: str,
    counterparty: str | None,
    source_amount: int,
    output_amount: int,
    output_token: str | None = LINK,
) -> PAEconomicAction:
    return PAEconomicAction(
        action_id="pa-action-id-test",
        kind=kind,
        chain_id=1,
        block_number=24_139_066,
        tx_hash="0x" + "f" * 64,
        log_index=0,
        contract_address=contract_address,
        contract_role=contract_role,
        source_token=LINK,
        output_token=output_token,
        source_amount=source_amount,
        output_amount=output_amount,
        counterparty=counterparty,
        source_event_signature="0x" * 1,
        raw_log_id="rl",
        decoded_event_id="de",
    )


def test_compute_pa_ledger_entry_id_deterministic_and_sha256() -> None:
    """Same inputs -> same id; matches sha256(canonical)."""
    a = compute_pa_ledger_entry_id("act1", 0)
    b = compute_pa_ledger_entry_id("act1", 0)
    assert isinstance(a, str)
    assert len(a) == 64
    assert a == b
    assert a == hashlib.sha256(b"pa_ledger_entry|act1|0").hexdigest()


def test_pa_ledger_fee_received_balanced() -> None:
    """FEE_RECEIVED: debit external_service, credit fee_aggregator."""
    action = _action(
        PAActionKind.FEE_RECEIVED,
        contract_address=PA_FEE_AGGREGATOR,
        contract_role="pa_fee_aggregator",
        counterparty="0x" + "ab" * 20,
        source_amount=100,
        output_amount=100,
    )
    entries = build_pa_ledger_entries(action)
    assert all(isinstance(e, PALedgerEntry) for e in entries)
    assert len(entries) == 2
    assert verify_pa_double_entry(entries) is True


def test_pa_ledger_swap_executed_balanced() -> None:
    """SWAP_EXECUTED: debit fee_aggregator, credit reserves (LINK leg)."""
    action = _action(
        PAActionKind.SWAP_EXECUTED,
        contract_address=PA_SWAP,
        contract_role="pa_swap_automator",
        counterparty=PA_RESERVES,
        source_amount=50,
        output_amount=100,
    )
    entries = build_pa_ledger_entries(action)
    assert len(entries) == 2
    assert verify_pa_double_entry(entries)
    # The LINK leg uses output_amount (the LINK ratio is what hits Reserves).
    assert all(e.amount_link == 100 for e in entries)


def test_pa_ledger_reserves_deposit_balanced() -> None:
    """RESERVES_DEPOSIT: debit upstream, credit pa_reserves."""
    action = _action(
        PAActionKind.RESERVES_DEPOSIT,
        contract_address=PA_RESERVES,
        contract_role="pa_reserves",
        counterparty=PA_SWAP,
        source_amount=200,
        output_amount=200,
    )
    entries = build_pa_ledger_entries(action)
    assert len(entries) == 2
    assert verify_pa_double_entry(entries)


def test_pa_ledger_service_fee_forwarded_balanced() -> None:
    """SERVICE_FEE_FORWARDED: debit contract, credit forwarded_to."""
    action = _action(
        PAActionKind.SERVICE_FEE_FORWARDED,
        contract_address=PA_FEE_AGGREGATOR,
        contract_role="pa_fee_aggregator",
        counterparty="0x" + "cd" * 20,
        source_amount=75,
        output_amount=75,
    )
    entries = build_pa_ledger_entries(action)
    assert len(entries) == 2
    assert verify_pa_double_entry(entries)


def test_pa_ledger_config_changed_emits_no_entries() -> None:
    """CONFIG_CHANGED is admin-only -> zero entries."""
    action = _action(
        PAActionKind.CONFIG_CHANGED,
        contract_address=PA_RESERVES,
        contract_role="pa_reserves",
        counterparty=None,
        source_amount=0,
        output_amount=0,
    )
    assert build_pa_ledger_entries(action) == []


def test_pa_ledger_zero_amount_emits_no_entries() -> None:
    """Action with zero amounts on both legs -> zero entries."""
    action = _action(
        PAActionKind.RESERVES_DEPOSIT,
        contract_address=PA_RESERVES,
        contract_role="pa_reserves",
        counterparty=PA_SWAP,
        source_amount=0,
        output_amount=0,
    )
    assert build_pa_ledger_entries(action) == []


def test_pa_verify_double_entry_imbalance_returns_false() -> None:
    """Manually-built imbalance is correctly flagged false."""
    e1 = PALedgerEntry(
        entry_id="e1",
        action_id="a1",
        entry_index=0,
        account="x",
        direction="debit",  # type: ignore[arg-type]
        amount_link=100,
        chain_id=1,
        block_number=0,
        tx_hash="0xt",
    )
    e2 = PALedgerEntry(
        entry_id="e2",
        action_id="a1",
        entry_index=1,
        account="y",
        direction="credit",  # type: ignore[arg-type]
        amount_link=50,
        chain_id=1,
        block_number=0,
        tx_hash="0xt",
    )
    # Use the actual PADirection enum so the equality check inside
    # verify_pa_double_entry works.
    from protocols.payment_abstraction.ledger_builder import PADirection

    e1 = PALedgerEntry(
        entry_id="e1",
        action_id="a1",
        entry_index=0,
        account="x",
        direction=PADirection.DEBIT,
        amount_link=100,
        chain_id=1,
        block_number=0,
        tx_hash="0xt",
    )
    e2 = PALedgerEntry(
        entry_id="e2",
        action_id="a1",
        entry_index=1,
        account="y",
        direction=PADirection.CREDIT,
        amount_link=50,
        chain_id=1,
        block_number=0,
        tx_hash="0xt",
    )
    assert verify_pa_double_entry([e1, e2]) is False
