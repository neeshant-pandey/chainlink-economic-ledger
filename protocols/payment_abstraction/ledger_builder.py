"""Payment Abstraction ledger construction.

PA actions translate to balanced double-entry rows just like Staking, but the
account names are different: source-chain service contracts on one side, the
PA Reserves / FeeAggregator / SwapAutomator on the other.

Per-tx invariant identical to Staking's: sum(debits) == sum(credits).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from protocols.payment_abstraction.semantics import PAActionKind, PAEconomicAction


class PADirection(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


@dataclass(frozen=True)
class PALedgerEntry:
    entry_id: str
    action_id: str
    entry_index: int
    account: str
    direction: PADirection
    amount_link: int
    chain_id: int
    block_number: int
    tx_hash: str


def compute_pa_ledger_entry_id(action_id: str, entry_index: int) -> str:
    """sha256-derived id for a PA ledger entry. Same shape as the Staking
    ledger id but a distinct namespace via the literal prefix."""
    canonical = f"pa_ledger_entry|{action_id}|{entry_index}"
    return hashlib.sha256(canonical.encode()).hexdigest()


def _entry(
    action: PAEconomicAction,
    idx: int,
    account: str,
    direction: PADirection,
    amount: int,
) -> PALedgerEntry:
    return PALedgerEntry(
        entry_id=compute_pa_ledger_entry_id(action.action_id, idx),
        action_id=action.action_id,
        entry_index=idx,
        account=account,
        direction=direction,
        amount_link=amount,
        chain_id=action.chain_id,
        block_number=action.block_number,
        tx_hash=action.tx_hash,
    )


def build_pa_ledger_entries(action: PAEconomicAction) -> list[PALedgerEntry]:
    """Produce balanced ledger entries for one PA action.

    Mappings:
      FEE_RECEIVED  : debit external_service, credit fee_aggregator
      SWAP_EXECUTED : debit fee_aggregator, credit reserves (output_amount in LINK)
      RESERVES_DEPOSIT: debit swap_automator, credit reserves
      SERVICE_FEE_FORWARDED: debit upstream, credit downstream
      CONFIG_CHANGED: no entries (admin event)
    """
    if action.kind == PAActionKind.CONFIG_CHANGED:
        return []
    if action.output_amount <= 0 and action.source_amount <= 0:
        return []

    counterparty = action.counterparty or "unknown"
    contract_acct = f"{action.contract_role}:{action.contract_address}"

    if action.kind == PAActionKind.FEE_RECEIVED:
        # An external service contract sent tokens to the FeeAggregator.
        amount = action.source_amount
        return [
            _entry(
                action,
                0,
                f"service_contract:{counterparty}",
                PADirection.DEBIT,
                amount,
            ),
            _entry(action, 1, contract_acct, PADirection.CREDIT, amount),
        ]
    if action.kind == PAActionKind.SWAP_EXECUTED:
        # FeeAggregator → SwapAutomator emits non-LINK; SwapAutomator returns
        # LINK to Reserves. Track the LINK leg only (amount = output_amount).
        amount = action.output_amount
        return [
            _entry(action, 0, contract_acct, PADirection.DEBIT, amount),
            _entry(
                action,
                1,
                f"pa_reserves:{action.output_token or 'link'}",
                PADirection.CREDIT,
                amount,
            ),
        ]
    if action.kind == PAActionKind.RESERVES_DEPOSIT:
        amount = action.output_amount or action.source_amount
        return [
            _entry(
                action,
                0,
                f"upstream:{counterparty}",
                PADirection.DEBIT,
                amount,
            ),
            _entry(action, 1, contract_acct, PADirection.CREDIT, amount),
        ]
    if action.kind == PAActionKind.SERVICE_FEE_FORWARDED:
        amount = action.source_amount
        return [
            _entry(action, 0, contract_acct, PADirection.DEBIT, amount),
            _entry(
                action,
                1,
                f"forwarded_to:{counterparty}",
                PADirection.CREDIT,
                amount,
            ),
        ]
    return []


def verify_pa_double_entry(entries: list[PALedgerEntry]) -> bool:
    """True iff sum(debits) == sum(credits) for the given list."""
    debits = sum(e.amount_link for e in entries if e.direction == PADirection.DEBIT)
    credits_total = sum(e.amount_link for e in entries if e.direction == PADirection.CREDIT)
    return debits == credits_total
