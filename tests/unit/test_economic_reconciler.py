"""Tests for `reconciliation.economic_reconciler`. Status × Method coverage."""

from __future__ import annotations

from protocols.staking_v02.semantics import ActionKind, EconomicAction
from reconciliation.economic_reconciler import (
    Method,
    Status,
    match_action_to_movements,
    match_tx_economics,
    reconcile_partition,
)
from reconciliation.movement_builder import TokenMovement

TX = "0x" + "1" * 64


def _action(amount: int = 100, kind: ActionKind = ActionKind.STAKE) -> EconomicAction:
    return EconomicAction(
        action_id="act_1",
        kind=kind,
        chain_id=1,
        block_number=100,
        tx_hash=TX,
        log_index=1,
        contract_address="0xpool",
        pool_role="community_staking_pool",
        wallet="0xwallet",
        amount_link=amount,
        source_event_signature="0xsig",
        raw_log_id="rl",
        decoded_event_id="de",
    )


def _movement(amount: int, source_priority: str = "log") -> TokenMovement:
    return TokenMovement(
        movement_id=f"mv|{amount}|{source_priority}",
        chain_id=1,
        block_number=100,
        tx_hash=TX,
        token_address="0xtoken",
        from_addr="0xa",
        to_addr="0xb",
        amount=amount,
        source_priority=source_priority,  # type: ignore[arg-type]
    )


def test_match_action_to_movements_exact() -> None:
    edges = match_action_to_movements(_action(100), [_movement(100)])
    assert len(edges) == 1
    assert edges[0].status == Status.EXACT
    assert edges[0].method == Method.EVENT_LOG


def test_match_action_to_movements_partial() -> None:
    """1 action of 100 + 2 movements summing to 100 → status=PARTIAL."""
    edges = match_action_to_movements(_action(100), [_movement(60), _movement(40)])
    assert len(edges) == 2
    assert all(e.status == Status.PARTIAL for e in edges)
    assert sum(e.allocated_amount for e in edges) == 100


def test_match_action_to_movements_unmatched() -> None:
    """No matching movement → status=UNMATCHED, movement_id=None."""
    edges = match_action_to_movements(_action(100), [_movement(50)])
    assert len(edges) == 1
    assert edges[0].status == Status.UNMATCHED
    assert edges[0].movement_id is None


def test_match_action_to_movements_not_expected() -> None:
    """UNSTAKE_REQUESTED → status=NOT_EXPECTED, method=None."""
    edges = match_action_to_movements(
        _action(0, ActionKind.UNSTAKE_REQUESTED),
        [],
    )
    assert len(edges) == 1
    assert edges[0].status == Status.NOT_EXPECTED
    assert edges[0].method is None


def test_match_action_to_movements_ambiguous() -> None:
    """Two equally-valid movements of the same amount → status=AMBIGUOUS."""
    edges = match_action_to_movements(_action(100), [_movement(100), _movement(100)])
    assert len(edges) == 1
    assert edges[0].status == Status.AMBIGUOUS


def test_match_method_distinguishes_log_vs_trace() -> None:
    """When matched movement is log-sourced → method=EVENT_LOG; trace → TRACE."""
    edges_log = match_action_to_movements(_action(100), [_movement(100, source_priority="log")])
    assert edges_log[0].method == Method.EVENT_LOG

    edges_trace = match_action_to_movements(_action(100), [_movement(100, source_priority="trace")])
    assert edges_trace[0].method == Method.TRACE


def test_match_tx_economics_detects_unexpected() -> None:
    """A movement with no matching action → tx report has unexpected_movements
    > 0 and one edge with status=UNEXPECTED, action_id=None."""
    actions = [_action(100)]
    movements = [_movement(100), _movement(50)]  # 100 matches; 50 unexpected
    recon = match_tx_economics(actions, movements)
    assert recon.unexpected_movements == 1
    unexpected = [e for e in recon.edges if e.status == Status.UNEXPECTED]
    assert len(unexpected) == 1
    assert unexpected[0].action_id is None


def test_reconcile_partition_returns_partition_recon() -> None:
    """End-to-end partition reconciliation."""
    actions_by_tx = {TX: [_action(100)]}
    movements_by_tx = {TX: [_movement(100)]}
    report = reconcile_partition(
        chain_id=1,
        from_block=100,
        to_block=200,
        actions_by_tx=actions_by_tx,
        movements_by_tx=movements_by_tx,
    )
    assert report.chain_id == 1
    assert report.block_range == (100, 200)
    assert report.pass_rate == 1.0
    assert report.counts_by_status[Status.EXACT] == 1
