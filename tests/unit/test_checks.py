"""public-function coverage for `reconciliation/checks.py`.

Each public function gets ≥1 test asserting the return type and one specific
behaviour stated in the docstring.

Edge-case (L3) tests:
  - `check_freshness` future-clock edge (last_block_timestamp > now)
  - `check_no_duplicate_event_ids` empty input edge
  - `check_unknown_signatures` zero-total edge
"""

from __future__ import annotations

from decoder.types import DecodeResult
from protocols.staking_v02.ledger_builder import (
    Direction,
    LedgerEntry,
)
from reconciliation.checks import (
    CheckResult,
    Severity,
    check_balance_consistency,
    check_freshness,
    check_ledger_balanced_per_tx,
    check_no_duplicate_event_ids,
    check_no_unmatched_economic_actions,
    check_pass_rate,
    check_unknown_signatures,
)
from reconciliation.economic_reconciler import (
    ActionMovementMatch,
    Method,
    PartitionReconciliation,
    Status,
    TxReconciliation,
)


def _partition(
    unmatched: int = 0,
    pass_rate: float = 1.0,
    n_tx: int = 1,
) -> PartitionReconciliation:
    tx = TxReconciliation(
        chain_id=1,
        block_number=18_000_000,
        tx_hash="0x" + "a" * 64,
        edges=[],
        actions_total=2,
        movements_total=2,
        unmatched_actions=unmatched,
        unexpected_movements=0,
        overall_status=Status.EXACT if unmatched == 0 else Status.UNMATCHED,
    )
    return PartitionReconciliation(
        partition_id="p1",
        chain_id=1,
        block_range=(18_000_000, 18_000_100),
        tx_recons=[tx] * n_tx,
        pass_rate=pass_rate,
        counts_by_status={Status.EXACT: 1},
    )


def test_check_no_unmatched_economic_actions_passes_when_zero() -> None:
    r = check_no_unmatched_economic_actions(_partition(unmatched=0))
    assert isinstance(r, CheckResult)
    assert r.passed is True
    assert r.severity == Severity.CRITICAL
    assert r.metric_value == 0


def test_check_no_unmatched_economic_actions_fails_when_any() -> None:
    r = check_no_unmatched_economic_actions(_partition(unmatched=3))
    assert r.passed is False
    assert r.metric_value == 3


def test_check_no_duplicate_event_ids_empty_input() -> None:
    """Edge: empty list -> passes with zero duplicates."""
    r = check_no_duplicate_event_ids([])
    assert isinstance(r, CheckResult)
    assert r.passed is True
    assert r.metric_value == 0


def test_check_no_duplicate_event_ids_distinct_passes() -> None:
    r = check_no_duplicate_event_ids(["a", "b", "c"])
    assert r.passed is True


def test_check_no_duplicate_event_ids_with_duplicate_fails() -> None:
    r = check_no_duplicate_event_ids(["a", "b", "a"])
    assert r.passed is False
    assert r.metric_value == 1


def test_check_freshness_within_lag_passes() -> None:
    r = check_freshness(last_block_timestamp=1000, now_timestamp=1050, max_lag_seconds=60)
    assert isinstance(r, CheckResult)
    assert r.passed is True
    assert r.metric_value == 50


def test_check_freshness_beyond_lag_fails() -> None:
    r = check_freshness(last_block_timestamp=1000, now_timestamp=2000, max_lag_seconds=60)
    assert r.passed is False
    assert r.metric_value == 1000


def test_check_freshness_future_clock_edge_case() -> None:
    """L3 edge case: last_block_timestamp > now_timestamp (clock skew between
    block proposer and verifier) -> lag clamped to 0 per the docstring."""
    r = check_freshness(last_block_timestamp=2000, now_timestamp=1000, max_lag_seconds=60)
    assert r.passed is True
    assert r.metric_value == 0


def test_check_unknown_signatures_below_threshold_passes() -> None:
    failures = [
        DecodeResult(
            raw_id="r1",
            success=False,
            decoded=None,
            failure_reason="abi_mismatch",
            failure_detail="x",
        ),
    ]
    r = check_unknown_signatures(failures, threshold_pct=10.0, total_attempts=100)
    assert isinstance(r, CheckResult)
    assert r.passed is True
    assert r.metric_value == 0.0  # zero unknown_topic in this batch


def test_check_unknown_signatures_above_threshold_fails() -> None:
    failures = [
        DecodeResult(
            raw_id=f"r{i}",
            success=False,
            decoded=None,
            failure_reason="unknown_topic",
            failure_detail="x",
        )
        for i in range(30)
    ]
    r = check_unknown_signatures(failures, threshold_pct=10.0, total_attempts=100)
    assert r.passed is False
    assert r.metric_value == 30.0  # 30%


def test_check_unknown_signatures_zero_attempts_edge() -> None:
    """L3 edge: total_attempts=None -> denominator defaults to len(failures);
    with zero failures, ratio is 0% (passes)."""
    r = check_unknown_signatures([], threshold_pct=5.0, total_attempts=None)
    assert r.passed is True
    assert r.metric_value == 0.0


def test_check_balance_consistency_passes_within_tolerance() -> None:
    r = check_balance_consistency({"0xpool1": 0, "0xpool2": 0})
    assert isinstance(r, CheckResult)
    assert r.passed is True
    assert r.metric_value == 0


def test_check_balance_consistency_fails_for_drift() -> None:
    r = check_balance_consistency({"0xpool1": 5, "0xpool2": -10}, tolerance_wei=0)
    assert r.passed is False
    assert r.metric_value == 2


def test_check_balance_consistency_tolerance_allows_small_drift() -> None:
    """Non-zero tolerance lets small diffs pass."""
    r = check_balance_consistency({"0xpool1": 3, "0xpool2": -2}, tolerance_wei=5)
    assert r.passed is True


def test_check_ledger_balanced_per_tx_balanced_passes() -> None:
    e1 = LedgerEntry(
        entry_id="e1",
        action_id="a1",
        entry_index=0,
        account="wallet:x",
        direction=Direction.DEBIT,
        amount_link=100,
        chain_id=1,
        block_number=18_000_000,
        tx_hash="0xt1",
    )
    e2 = LedgerEntry(
        entry_id="e2",
        action_id="a1",
        entry_index=1,
        account="pool:y",
        direction=Direction.CREDIT,
        amount_link=100,
        chain_id=1,
        block_number=18_000_000,
        tx_hash="0xt1",
    )
    r = check_ledger_balanced_per_tx([e1, e2])
    assert isinstance(r, CheckResult)
    assert r.passed is True


def test_check_ledger_balanced_per_tx_unbalanced_fails() -> None:
    e1 = LedgerEntry(
        entry_id="e1",
        action_id="a1",
        entry_index=0,
        account="wallet:x",
        direction=Direction.DEBIT,
        amount_link=100,
        chain_id=1,
        block_number=18_000_000,
        tx_hash="0xt2",
    )
    # Missing credit -> imbalanced
    r = check_ledger_balanced_per_tx([e1])
    assert r.passed is False
    assert r.metric_value >= 1


def test_check_pass_rate_above_min_passes() -> None:
    r = check_pass_rate(_partition(pass_rate=0.99), min_pass_rate=0.95)
    assert isinstance(r, CheckResult)
    assert r.passed is True


def test_check_pass_rate_below_min_fails() -> None:
    r = check_pass_rate(_partition(pass_rate=0.80), min_pass_rate=0.95)
    assert r.passed is False


# Suppress unused-import warnings for symbols imported for typing rigor.
_ = (ActionMovementMatch, Method)
