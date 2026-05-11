"""Data-quality check functions invoked by the reconciliation_check Airflow DAG.

Each check returns a CheckResult; the DAG decides whether to fail (blocking),
alert (informational), or both.

Distinction: `monitoring/metrics.py` emits time-series metrics; this module
emits discrete pass/fail check results.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from decoder.types import DecodeResult
from reconciliation.economic_reconciler import PartitionReconciliation, Status


class Severity(StrEnum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    severity: Severity
    detail: str
    metric_value: float | int | None = None


def check_no_unmatched_economic_actions(
    report: PartitionReconciliation,
) -> CheckResult:
    """Critical check: any tx in the partition has UNMATCHED actions → fail.

    Reports the number of unmatched actions across the partition.
    """
    unmatched = sum(r.unmatched_actions for r in report.tx_recons)
    return CheckResult(
        name="no_unmatched_economic_actions",
        passed=(unmatched == 0),
        severity=Severity.CRITICAL,
        detail=f"unmatched_action_count={unmatched}",
        metric_value=unmatched,
    )


def check_no_duplicate_event_ids(decoded_event_ids: list[str]) -> CheckResult:
    """Critical: every decoded_event_id must be unique across the partition.

    Duplicates indicate either a hashing collision or a replay that re-wrote a
    row with a different id (the lineage signal).
    """
    seen: set[str] = set()
    dupes: list[str] = []
    for ev_id in decoded_event_ids:
        if ev_id in seen:
            dupes.append(ev_id)
        seen.add(ev_id)
    return CheckResult(
        name="no_duplicate_event_ids",
        passed=(len(dupes) == 0),
        severity=Severity.CRITICAL,
        detail=(f"duplicate count={len(dupes)}; first 5={dupes[:5]}" if dupes else "no duplicates"),
        metric_value=len(dupes),
    )


def check_freshness(
    last_block_timestamp: int,
    now_timestamp: int,
    max_lag_seconds: int,
) -> CheckResult:
    """Warn-level check: data is fresh within `max_lag_seconds` of `now_timestamp`.

    Edge case: if `last_block_timestamp` is in the future (clock skew between
    block proposer and verifier), report lag=0.
    """
    lag = max(0, now_timestamp - last_block_timestamp)
    return CheckResult(
        name="freshness",
        passed=(lag <= max_lag_seconds),
        severity=Severity.WARN,
        detail=f"lag_seconds={lag}, max_allowed={max_lag_seconds}",
        metric_value=lag,
    )


def check_unknown_signatures(
    decode_failures: list[DecodeResult],
    threshold_pct: float,
    total_attempts: int | None = None,
) -> CheckResult:
    """Fails if `count(failure_reason='unknown_topic') / total_attempts >
    threshold`.

    `total_attempts` is the denominator (number of decode attempts in the
    partition). If None, we assume `len(decode_failures)` is the denominator
    (which makes the ratio always 1.0 when there are any failures — caller
    should pass an accurate value).
    """
    if total_attempts is None:
        total_attempts = max(1, len(decode_failures))

    unknowns = sum(1 for r in decode_failures if r.failure_reason == "unknown_topic")
    pct = (unknowns / total_attempts) * 100 if total_attempts > 0 else 0.0

    return CheckResult(
        name="unknown_signatures_below_threshold",
        passed=(pct <= threshold_pct),
        severity=Severity.WARN,
        detail=(
            f"unknown_topic_count={unknowns}, total={total_attempts}, "
            f"pct={pct:.3f}, threshold={threshold_pct}"
        ),
        metric_value=pct,
    )


def check_balance_consistency(
    pool_diffs: dict[str, int],
    tolerance_wei: int = 0,
) -> CheckResult:
    """Critical: every pool's |diff| must be ≤ tolerance_wei.

    `pool_diffs` maps `pool_address → (observed - expected)`. A non-zero diff
    means a movement is missing or one is double-counted.
    """
    bad: list[tuple[str, int]] = [
        (addr, diff) for addr, diff in pool_diffs.items() if abs(diff) > tolerance_wei
    ]
    return CheckResult(
        name="balance_consistency",
        passed=(len(bad) == 0),
        severity=Severity.CRITICAL,
        detail=(
            f"{len(bad)} pool(s) inconsistent: " + ", ".join(f"{a}=delta {d}" for a, d in bad[:5])
            if bad
            else "all pools consistent"
        ),
        metric_value=len(bad),
    )


def check_ledger_balanced_per_tx(entries: list[object]) -> CheckResult:
    """For every tx, sum(debits) == sum(credits). Reports first 10 violators
    in `detail`.

    `entries` is typed as `list[object]` to avoid a hard import on
    `protocols.staking_v02.ledger_builder.LedgerEntry`; we duck-type the
    needed fields.
    """
    by_tx: dict[str, dict[str, int]] = {}
    for entry in entries:
        tx_hash = getattr(entry, "tx_hash", "")
        direction = getattr(entry, "direction", "")
        amount = int(getattr(entry, "amount_link", 0))
        if not tx_hash:
            continue
        bucket = by_tx.setdefault(tx_hash, {"debit": 0, "credit": 0})
        # direction may be Direction enum or string
        d_str = direction.value if hasattr(direction, "value") else str(direction)
        if d_str == "debit":
            bucket["debit"] += amount
        elif d_str == "credit":
            bucket["credit"] += amount

    violators: list[tuple[str, int, int]] = []
    for tx_hash, sums in by_tx.items():
        if sums["debit"] != sums["credit"]:
            violators.append((tx_hash, sums["debit"], sums["credit"]))

    return CheckResult(
        name="ledger_balanced_per_tx",
        passed=(len(violators) == 0),
        severity=Severity.CRITICAL,
        detail=(
            "first 10 violators: "
            + "; ".join(f"{tx}: debit={d}/credit={c}" for tx, d, c in violators[:10])
            if violators
            else "all txs balanced"
        ),
        metric_value=len(violators),
    )


def check_pass_rate(report: PartitionReconciliation, min_pass_rate: float = 0.95) -> CheckResult:
    """Warn-level: per-partition pass_rate must be at least `min_pass_rate`."""
    return CheckResult(
        name="reconciliation_pass_rate",
        passed=(report.pass_rate >= min_pass_rate),
        severity=Severity.WARN,
        detail=(
            f"pass_rate={report.pass_rate:.4f}, min_required={min_pass_rate}, "
            f"counts={ {s.value: c for s, c in report.counts_by_status.items()} }"
        ),
        metric_value=report.pass_rate,
    )


# Re-export Status for convenience (so callers wiring the DAG don't have to
# import it from economic_reconciler).
__all__ = [
    "CheckResult",
    "Severity",
    "Status",
    "check_balance_consistency",
    "check_freshness",
    "check_ledger_balanced_per_tx",
    "check_no_duplicate_event_ids",
    "check_no_unmatched_economic_actions",
    "check_pass_rate",
    "check_unknown_signatures",
]
