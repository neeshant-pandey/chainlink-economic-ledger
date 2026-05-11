"""Realized APY computation from reconciled ledger entries.

Realized APY is the per-pool annualized yield computed from observed reward
distributions over time-weighted principal — NOT the protocol's advertised
target rate. The two diverge whenever stakers don't claim rewards (the
distributions land but accrual hasn't been claimed) or when a pool is
oversubscribed (rewards diluted across more principal).

Inputs are typed as plain dicts (matching the dbt mart row shape) so this
module can be exercised without standing up BigQuery. The Python signatures
are the ones the dbt analytics mart's macro mirrors.
"""

from __future__ import annotations

from dataclasses import dataclass

SECONDS_PER_YEAR = 365 * 24 * 3600


@dataclass(frozen=True)
class APYDataPoint:
    """One row in the apy_realized_by_pool mart."""

    pool_address: str
    snapshot_date: str  # ISO date, e.g. "2026-05-01"
    cumulative_principal_link_seconds: int  # Σ(principal × seconds it was staked)
    cumulative_rewards_link: int  # Σ rewards distributed up to snapshot_date
    realized_apy: float  # rewards / time-weighted-principal, annualized


def compute_time_weighted_principal(
    stake_events: list[dict],
    snapshot_unix: int,
) -> int:
    """Σ(principal_i × min(snapshot_unix, end_i) - start_i) for each stake i.

    `stake_events` rows must contain `start_unix`, `principal`, and optionally
    `end_unix` (open-ended ⇒ use snapshot_unix).

    Returns the integral in `link × seconds`. Divide by SECONDS_PER_YEAR to
    get the time-weighted average principal (link).
    """
    total = 0
    for ev in stake_events:
        principal = int(ev.get("principal", 0))
        start = int(ev.get("start_unix", 0))
        end = int(ev.get("end_unix", snapshot_unix) or snapshot_unix)
        end = min(end, snapshot_unix)
        if end <= start or principal <= 0:
            continue
        total += principal * (end - start)
    return total


def compute_realized_apy(
    rewards_link: int,
    time_weighted_principal_link_seconds: int,
) -> float:
    """APY = (rewards / avg_principal) × (SECONDS_PER_YEAR / Δt)
    But since `time_weighted_principal_link_seconds` already has the time
    dimension folded in:

        APY = rewards_link × SECONDS_PER_YEAR / time_weighted_principal_link_seconds

    Returns 0.0 when the denominator is 0.
    """
    if time_weighted_principal_link_seconds <= 0:
        return 0.0
    return float(rewards_link * SECONDS_PER_YEAR) / float(time_weighted_principal_link_seconds)


def compute_apy_for_pool(
    pool_address: str,
    snapshot_date: str,
    snapshot_unix: int,
    stake_events: list[dict],
    reward_events: list[dict],
) -> APYDataPoint:
    """Roll a pool's stakes + rewards into a single APYDataPoint."""
    twp = compute_time_weighted_principal(stake_events, snapshot_unix)
    cumulative_rewards = sum(
        int(r.get("amount_link", 0))
        for r in reward_events
        if int(r.get("ts_unix", 0)) <= snapshot_unix
    )
    apy = compute_realized_apy(cumulative_rewards, twp)
    return APYDataPoint(
        pool_address=pool_address.lower(),
        snapshot_date=snapshot_date,
        cumulative_principal_link_seconds=twp,
        cumulative_rewards_link=cumulative_rewards,
        realized_apy=apy,
    )
