"""Maps decoded Chainlink Staking v0.2 events into typed `EconomicAction` records.

Encodes protocol semantics: which event constitutes a stake, whether a
v0.1→v0.2 Migrated event produces one action or two (debit + credit), whether
`Slashed(address,uint256)` carries an immediate Transfer or not.

Event signatures and contract semantics: `docs/data-model.md#staking-v02-events`.
Where a signature is not yet finalized in the ABI registry, we accept by event
NAME (case-sensitive); the registry is the runtime source of truth for signatures.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from decoder.contract_registry import ContractRegistry
from decoder.types import DecodedEvent


class ActionKind(StrEnum):
    STAKE = "stake"
    UNSTAKE_REQUESTED = "unstake_requested"
    UNSTAKE_FINALIZED = "unstake_finalized"
    REWARD_CLAIMED = "reward_claimed"
    REWARD_ACCRUED = "reward_accrued"  # off-token, ledger-only
    SLASHED = "slashed"
    MIGRATED_FROM_V01 = "migrated_from_v01"
    POOL_CONFIG_CHANGED = "pool_config_changed"


# Map from canonical event name → ActionKind. Multiple event names can map to
# the same kind (e.g. "Staked" and "MigratedAndStaked").
EVENT_NAME_TO_KIND: dict[str, ActionKind] = {
    "Staked": ActionKind.STAKE,
    "Stake": ActionKind.STAKE,
    "UnstakeRequested": ActionKind.UNSTAKE_REQUESTED,
    "UnbondingPeriodStarted": ActionKind.UNSTAKE_REQUESTED,
    "Unstaked": ActionKind.UNSTAKE_FINALIZED,
    "UnstakeFinalized": ActionKind.UNSTAKE_FINALIZED,
    "Withdrawn": ActionKind.UNSTAKE_FINALIZED,
    "RewardClaimed": ActionKind.REWARD_CLAIMED,
    "RewardsClaimed": ActionKind.REWARD_CLAIMED,
    "RewardAdded": ActionKind.REWARD_ACCRUED,
    "RewardAccrued": ActionKind.REWARD_ACCRUED,
    "Slashed": ActionKind.SLASHED,
    "Migrated": ActionKind.MIGRATED_FROM_V01,
    "MigratedFromV01": ActionKind.MIGRATED_FROM_V01,
    "PoolConfigChanged": ActionKind.POOL_CONFIG_CHANGED,
    "ConfigSet": ActionKind.POOL_CONFIG_CHANGED,
}


@dataclass(frozen=True)
class EconomicAction:
    """The protocol-meaningful unit. Produced from a single DecodedEvent."""

    action_id: str  # idempotency grain 5
    kind: ActionKind
    chain_id: int
    block_number: int
    tx_hash: str
    log_index: int
    contract_address: str
    pool_role: str  # e.g. "community_pool", "operator_pool"
    wallet: str | None  # actor wallet; None for pool-level events
    amount_link: int  # raw uint256; may be 0 for non-token events
    source_event_signature: str  # topic0
    raw_log_id: str
    decoded_event_id: str


@dataclass(frozen=True)
class EnrichedAction:
    """EconomicAction + denormalized context for downstream marts."""

    action: EconomicAction
    pool_address: str
    pool_role: str
    contract_phase_version: str


def compute_action_id(decoded: DecodedEvent, kind: ActionKind) -> str:
    """SHA-256 of `(decoded_event_id, kind)`. Most events produce a single
    action; the kind suffix disambiguates the rare case where one event yields
    multiple actions (e.g. migration → debit on v01 + credit on v02).
    """
    canonical = f"action|{decoded.decoded_event_id}|{kind.value}"
    return hashlib.sha256(canonical.encode()).hexdigest()


def _extract_amount_link(decoded: DecodedEvent) -> int:
    """Pull the LINK amount out of common decoded-event shapes.

    Looks at indexed_params first (some events index amount), then
    data_params. Common parameter names: amount, value, newPrincipal,
    principal, reward, slashedAmount.
    """
    candidate_keys = (
        "amount",
        "value",
        "newPrincipal",
        "principal",
        "reward",
        "slashedAmount",
        "slashedPrincipal",
        "rewardAmount",
        "stakedAmount",
        "withdrawnAmount",
    )
    for source in (decoded.indexed_params, decoded.data_params):
        for k in candidate_keys:
            if k in source and source[k] is not None:
                return int(source[k])
    return 0


def _extract_wallet(decoded: DecodedEvent) -> str | None:
    """Pull the actor wallet from common event parameter names."""
    candidate_keys = ("staker", "wallet", "user", "operator", "account", "from")
    for source in (decoded.indexed_params, decoded.data_params):
        for k in candidate_keys:
            v = source.get(k)
            if v is not None:
                return str(v).lower()
    return None


def classify_event_as_action(
    decoded: DecodedEvent,
    registry: ContractRegistry,
) -> list[EconomicAction]:
    """Returns 0..N actions per event.

    Most events return exactly one. Migration events return two (one debit on
    the v0.1 pool, one credit on the v0.2 pool). Events from a contract role
    we don't model return zero.

    Implementation: lookup by `event_name` first (the canonical mapping),
    falling back to nothing if unknown. Pool role is taken from the contract
    registry; if the contract isn't registered, default to "unknown".
    """
    role = registry.role(decoded.contract_address) or "unknown"
    if role == "unknown":
        # Contract not in registry → no action emitted. The decode_failures
        # layer will surface this as an unregistered_contract.
        return []

    kind = EVENT_NAME_TO_KIND.get(decoded.event_name)
    if kind is None:
        return []

    amount = _extract_amount_link(decoded)
    wallet = _extract_wallet(decoded)

    base_action = EconomicAction(
        action_id=compute_action_id(decoded, kind),
        kind=kind,
        chain_id=decoded.chain_id,
        block_number=decoded.block_number,
        tx_hash=decoded.tx_hash,
        log_index=decoded.log_index,
        contract_address=decoded.contract_address,
        pool_role=role,
        wallet=wallet,
        amount_link=amount,
        source_event_signature=decoded.event_signature,
        raw_log_id=decoded.raw_log_id,
        decoded_event_id=decoded.decoded_event_id,
    )

    if kind == ActionKind.MIGRATED_FROM_V01:
        # Migration produces two actions: a credit on v0.2 (the base) and a
        # debit on v0.1 (we synthesize a paired action with a different
        # action_id by extending the canonical key).
        v01_action_id = hashlib.sha256(
            f"action|{decoded.decoded_event_id}|migrated_v01_debit".encode()
        ).hexdigest()
        v01_action = EconomicAction(
            action_id=v01_action_id,
            kind=kind,  # same kind, different role
            chain_id=base_action.chain_id,
            block_number=base_action.block_number,
            tx_hash=base_action.tx_hash,
            log_index=base_action.log_index,
            contract_address=base_action.contract_address,
            pool_role="staking_pool_v01",
            wallet=base_action.wallet,
            amount_link=base_action.amount_link,
            source_event_signature=base_action.source_event_signature,
            raw_log_id=base_action.raw_log_id,
            decoded_event_id=base_action.decoded_event_id,
        )
        return [v01_action, base_action]

    return [base_action]


def enrich_action_with_context(
    action: EconomicAction,
    registry: ContractRegistry,
) -> EnrichedAction:
    """Denormalize the contract phase / role onto the action for mart writes.

    Returns a new EnrichedAction; does not mutate the input.
    """
    role = registry.role(action.contract_address) or action.pool_role
    try:
        phase = registry.get_phase(action.contract_address, action.block_number)
        version = phase.abi_version
    except KeyError:
        version = "unknown"
    return EnrichedAction(
        action=action,
        pool_address=action.contract_address,
        pool_role=role,
        contract_phase_version=version,
    )
