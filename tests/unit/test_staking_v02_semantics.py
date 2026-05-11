"""Tests for `protocols.staking_v02.semantics`. Event → action classification."""

from __future__ import annotations

from decoder.types import DecodedEvent
from protocols.staking_v02.semantics import (
    ActionKind,
    classify_event_as_action,
    compute_action_id,
    enrich_action_with_context,
)


class _Reg:
    """Minimal ContractRegistry stand-in for tests."""

    def __init__(self, role_map: dict[str, str]) -> None:
        self._roles = {k.lower(): v for k, v in role_map.items()}

    def role(self, address: str) -> str | None:
        return self._roles.get(address.lower())

    def get_phase(self, address: str, block_number: int) -> object:
        from decoder.types import Phase

        return Phase(
            contract_address=address.lower(),
            abi_version="v0.2.0",
            from_block=0,
            to_block=None,
        )


def _decoded(event_name: str, **kwargs) -> DecodedEvent:  # type: ignore[no-untyped-def]
    return DecodedEvent(
        raw_log_id="rl",
        decoded_event_id="de",
        chain_id=1,
        block_number=100,
        tx_hash="0xtx",
        log_index=0,
        contract_address=kwargs.get("contract", "0xpool"),
        event_name=event_name,
        event_signature="0xsig",
        indexed_params=kwargs.get("indexed", {}),
        data_params=kwargs.get("data", {}),
    )


def test_classify_staked_event() -> None:
    decoded = _decoded(
        "Staked",
        indexed={"staker": "0xabc"},
        data={"newPrincipal": 100},
    )
    actions = classify_event_as_action(decoded, _Reg({"0xpool": "community_staking_pool"}))
    assert len(actions) == 1
    assert actions[0].kind == ActionKind.STAKE
    assert actions[0].amount_link == 100
    assert actions[0].wallet == "0xabc"


def test_classify_unstake_requested_no_token_expected() -> None:
    decoded = _decoded(
        "UnstakeRequested",
        indexed={"staker": "0xabc"},
        data={"amount": 50},
    )
    actions = classify_event_as_action(decoded, _Reg({"0xpool": "community_staking_pool"}))
    assert len(actions) == 1
    assert actions[0].kind == ActionKind.UNSTAKE_REQUESTED


def test_classify_slashed_event() -> None:
    decoded = _decoded(
        "Slashed",
        indexed={"operator": "0xop"},
        data={"amount": 30},
    )
    actions = classify_event_as_action(decoded, _Reg({"0xpool": "operator_staking_pool"}))
    assert len(actions) == 1
    assert actions[0].kind == ActionKind.SLASHED
    assert actions[0].amount_link == 30


def test_classify_migrated_produces_two_actions() -> None:
    decoded = _decoded(
        "Migrated",
        indexed={"staker": "0xabc"},
        data={"amount": 50},
    )
    actions = classify_event_as_action(decoded, _Reg({"0xpool": "community_staking_pool"}))
    assert len(actions) == 2
    roles = {a.pool_role for a in actions}
    assert "staking_pool_v01" in roles
    # The base role from the registry is also present
    assert "community_staking_pool" in roles
    # Action ids must differ
    assert actions[0].action_id != actions[1].action_id


def test_classify_unknown_event_returns_empty() -> None:
    decoded = _decoded("WeirdEvent", indexed={}, data={})
    assert classify_event_as_action(decoded, _Reg({"0xpool": "community_staking_pool"})) == []


def test_classify_unknown_contract_returns_empty() -> None:
    decoded = _decoded("Staked", indexed={"staker": "0xabc"}, data={"amount": 1})
    # Registry has no entry for 0xpool
    assert classify_event_as_action(decoded, _Reg({})) == []


def test_compute_action_id_distinct_per_kind_for_same_event() -> None:
    decoded = _decoded(
        "Migrated",
        indexed={"staker": "0xabc"},
        data={"amount": 1},
    )
    a = compute_action_id(decoded, ActionKind.STAKE)
    b = compute_action_id(decoded, ActionKind.MIGRATED_FROM_V01)
    assert a != b


def test_enrich_action_with_context() -> None:
    decoded = _decoded("Staked", indexed={"staker": "0xabc"}, data={"amount": 1})
    actions = classify_event_as_action(decoded, _Reg({"0xpool": "community_staking_pool"}))
    enriched = enrich_action_with_context(actions[0], _Reg({"0xpool": "community_staking_pool"}))
    assert enriched.pool_role == "community_staking_pool"
    assert enriched.contract_phase_version == "v0.2.0"
