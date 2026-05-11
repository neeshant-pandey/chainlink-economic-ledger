"""Payment Abstraction (PA) protocol semantics.

PA is the hero protocol. It moves LINK fees from any Chainlink service (VRF,
Functions, Data Streams, CCIP) into the Reserve via:

    service contract → FeeAggregator → SwapAutomator → Reserves

Mainnet contract addresses (lowercase canonical form internally; mixed-case
checksum for display only):

    Reserves        0x5680681ed3767b96914ce741a308155c7fb9171d
    FeeAggregator   0xd6e39d42acee7abcc460e6ea78a0844a0980e78f
    SwapAutomator   0x36e827ba2b270535ca1b099a6ba2b280ddc0315e

PA action kinds we model:

    FEE_RECEIVED   — FeeAggregator receives LINK or non-LINK service fee
    SWAP_EXECUTED  — SwapAutomator swaps non-LINK fee → LINK
    RESERVES_DEPOSIT — LINK lands in Reserves
    SERVICE_FEE_FORWARDED — internal forwarding hop (not always logged)

Each event maps to exactly one EconomicAction. There is no migration-style
pair like Staking has.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from decoder.contract_registry import ContractRegistry
from decoder.types import DecodedEvent


class PAActionKind(StrEnum):
    FEE_RECEIVED = "pa_fee_received"
    SWAP_EXECUTED = "pa_swap_executed"
    RESERVES_DEPOSIT = "pa_reserves_deposit"
    SERVICE_FEE_FORWARDED = "pa_service_fee_forwarded"
    CONFIG_CHANGED = "pa_config_changed"


# Canonical PA mainnet addresses (lowercase) — reproduced from
# config/contracts/payment_abstraction.yaml; centralized here so the
# protocol layer can validate against config quickly.
PA_RESERVES_ADDRESS = "0x5680681ed3767b96914ce741a308155c7fb9171d"
PA_FEE_AGGREGATOR_ADDRESS = "0xd6e39d42acee7abcc460e6ea78a0844a0980e78f"
PA_SWAP_AUTOMATOR_ADDRESS = "0x36e827ba2b270535ca1b099a6ba2b280ddc0315e"


# Map from PA event name → action kind. Multiple event names can map to one
# kind (the contract upgrades may rename events; we accept synonyms).
PA_EVENT_NAME_TO_KIND: dict[str, PAActionKind] = {
    "FeeReceived": PAActionKind.FEE_RECEIVED,
    "FeesReceived": PAActionKind.FEE_RECEIVED,
    "FeeAggregated": PAActionKind.FEE_RECEIVED,
    "SwapExecuted": PAActionKind.SWAP_EXECUTED,
    "Swap": PAActionKind.SWAP_EXECUTED,
    "Deposited": PAActionKind.RESERVES_DEPOSIT,
    "ReservesDeposit": PAActionKind.RESERVES_DEPOSIT,
    "Withdrawn": PAActionKind.RESERVES_DEPOSIT,  # withdrawal IN to reserves
    "ServiceFeeForwarded": PAActionKind.SERVICE_FEE_FORWARDED,
    "Forwarded": PAActionKind.SERVICE_FEE_FORWARDED,
    "ConfigSet": PAActionKind.CONFIG_CHANGED,
    "ConfigUpdated": PAActionKind.CONFIG_CHANGED,
}


@dataclass(frozen=True)
class PAEconomicAction:
    """PA-specific economic action. Distinct dataclass from Staking's so the
    types remain narrow."""

    action_id: str
    kind: PAActionKind
    chain_id: int
    block_number: int
    tx_hash: str
    log_index: int
    contract_address: str
    contract_role: str  # "pa_reserves" | "pa_fee_aggregator" | "pa_swap_automator"
    source_token: str | None  # the token coming in (None if N/A)
    output_token: str | None  # the token going out (None if not a swap)
    source_amount: int  # raw uint256
    output_amount: int  # raw uint256 (for swaps); == source_amount if not a swap
    counterparty: str | None  # the other side of the swap / deposit (lowercase)
    source_event_signature: str
    raw_log_id: str
    decoded_event_id: str


def compute_pa_action_id(decoded: DecodedEvent, kind: PAActionKind) -> str:
    """PA action id = sha256("pa_action|<decoded_event_id>|<kind>"). Distinct
    namespace from Staking actions so a future cross-protocol query can't
    accidentally collide."""
    canonical = f"pa_action|{decoded.decoded_event_id}|{kind.value}"
    return hashlib.sha256(canonical.encode()).hexdigest()


def _pull_token(decoded: DecodedEvent, *names: str) -> str | None:
    for n in names:
        v = decoded.indexed_params.get(n) or decoded.data_params.get(n)
        if v is not None:
            return str(v).lower()
    return None


def _pull_amount(decoded: DecodedEvent, *names: str) -> int:
    for n in names:
        for source in (decoded.indexed_params, decoded.data_params):
            v = source.get(n)
            if v is not None:
                return int(v)
    return 0


def classify_pa_event_as_action(
    decoded: DecodedEvent,
    registry: ContractRegistry,
) -> list[PAEconomicAction]:
    """Returns 0..1 PA actions per event.

    The PA contracts are recognized by role:
      - role "pa_reserves" → events here become RESERVES_DEPOSIT
      - role "pa_fee_aggregator" → FEE_RECEIVED / SERVICE_FEE_FORWARDED
      - role "pa_swap_automator" → SWAP_EXECUTED

    If the event name resolves to a kind, we emit one PAEconomicAction.
    Otherwise we return [].
    """
    role = registry.role(decoded.contract_address) or ""
    if not role.startswith("pa_"):
        return []

    kind = PA_EVENT_NAME_TO_KIND.get(decoded.event_name)
    if kind is None:
        return []

    source_token = _pull_token(decoded, "sourceToken", "tokenIn", "token")
    output_token = _pull_token(decoded, "outputToken", "tokenOut", "linkToken")
    source_amount = _pull_amount(decoded, "sourceAmount", "amountIn", "amount", "value")
    output_amount = _pull_amount(decoded, "outputAmount", "amountOut", "linkAmount")
    if output_amount == 0:
        # Many events carry a single `amount` (no swap dimension); reuse it
        output_amount = source_amount

    counterparty = _pull_token(decoded, "from", "sender", "to", "recipient", "depositor")

    action = PAEconomicAction(
        action_id=compute_pa_action_id(decoded, kind),
        kind=kind,
        chain_id=decoded.chain_id,
        block_number=decoded.block_number,
        tx_hash=decoded.tx_hash,
        log_index=decoded.log_index,
        contract_address=decoded.contract_address,
        contract_role=role,
        source_token=source_token,
        output_token=output_token,
        source_amount=source_amount,
        output_amount=output_amount,
        counterparty=counterparty,
        source_event_signature=decoded.event_signature,
        raw_log_id=decoded.raw_log_id,
        decoded_event_id=decoded.decoded_event_id,
    )
    return [action]


def is_pa_contract_address(address: str) -> bool:
    """Quick check whether a given address is one of the three core PA
    contracts. Useful in extractor predicates."""
    addr = address.lower()
    return addr in {
        PA_RESERVES_ADDRESS,
        PA_FEE_AGGREGATOR_ADDRESS,
        PA_SWAP_AUTOMATOR_ADDRESS,
    }


def pa_role_of(address: str) -> str | None:
    """Map a known PA address to its role. None if unknown."""
    addr = address.lower()
    if addr == PA_RESERVES_ADDRESS:
        return "pa_reserves"
    if addr == PA_FEE_AGGREGATOR_ADDRESS:
        return "pa_fee_aggregator"
    if addr == PA_SWAP_AUTOMATOR_ADDRESS:
        return "pa_swap_automator"
    return None
