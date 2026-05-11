"""Reward distribution analytics.

Answers: how efficient is reward distribution? What fraction of distributed
rewards has been claimed vs is still accrued (off-token, sitting in storage)?
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DistributionEfficiency:
    pool_address: str
    snapshot_date: str
    rewards_distributed: int  # Σ RewardAdded
    rewards_claimed: int  # Σ RewardClaimed
    claim_ratio: float  # claimed / distributed; 0..1


def compute_distribution_efficiency(
    pool_address: str,
    snapshot_date: str,
    distributed_events: list[dict],
    claimed_events: list[dict],
) -> DistributionEfficiency:
    """Roll RewardAdded vs RewardClaimed into a single ratio for a pool."""
    distributed = sum(int(e.get("amount_link", 0)) for e in distributed_events)
    claimed = sum(int(e.get("amount_link", 0)) for e in claimed_events)
    ratio = (claimed / distributed) if distributed > 0 else 0.0
    return DistributionEfficiency(
        pool_address=pool_address.lower(),
        snapshot_date=snapshot_date,
        rewards_distributed=distributed,
        rewards_claimed=claimed,
        claim_ratio=ratio,
    )


def compute_unclaimed_reward_balance(
    distributed_events: list[dict],
    claimed_events: list[dict],
) -> int:
    """The amount of LINK sitting in the reward vault as accrued-but-unclaimed.

    Equal to `Σ distributed - Σ claimed` for the pool. Negative values
    indicate a bug (claims exceed distributions).
    """
    distributed = sum(int(e.get("amount_link", 0)) for e in distributed_events)
    claimed = sum(int(e.get("amount_link", 0)) for e in claimed_events)
    return distributed - claimed
