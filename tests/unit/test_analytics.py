"""public-function coverage for `analytics/`.

Each public function in `analytics/{apy_realized, reward_distribution,
pa_fee_attribution}` gets at least one unit test that:
  - calls the function with realistic input
  - asserts the return type matches the type hint
  - asserts ≥1 specific value matches the docstring contract
"""

from __future__ import annotations

from analytics.apy_realized import (
    SECONDS_PER_YEAR,
    APYDataPoint,
    compute_apy_for_pool,
    compute_realized_apy,
    compute_time_weighted_principal,
)
from analytics.pa_fee_attribution import (
    KNOWN_SERVICE_ADDRESSES,
    FeeAttribution,
    attribute_pa_fees,
    classify_service,
)
from analytics.reward_distribution import (
    DistributionEfficiency,
    compute_distribution_efficiency,
    compute_unclaimed_reward_balance,
)

# --- apy_realized ---------------------------------------------------------


def test_compute_time_weighted_principal_basic() -> None:
    """One stake of 100 LINK active for the full window."""
    events = [{"principal": 100, "start_unix": 0, "end_unix": 3600}]
    twp = compute_time_weighted_principal(events, snapshot_unix=3600)
    assert isinstance(twp, int)
    assert twp == 100 * 3600


def test_compute_time_weighted_principal_open_ended_stake() -> None:
    """If `end_unix` is missing the stake is open-ended; the snapshot caps it."""
    events = [{"principal": 50, "start_unix": 0}]
    twp = compute_time_weighted_principal(events, snapshot_unix=1000)
    assert twp == 50 * 1000


def test_compute_time_weighted_principal_ignores_invalid_rows() -> None:
    """Zero / negative principal or zero-length window contributes nothing."""
    events = [
        {"principal": 0, "start_unix": 0, "end_unix": 1000},
        {"principal": 100, "start_unix": 1000, "end_unix": 1000},  # window=0
    ]
    twp = compute_time_weighted_principal(events, snapshot_unix=1000)
    assert twp == 0


def test_compute_realized_apy_basic() -> None:
    """APY = rewards * SECONDS_PER_YEAR / time_weighted_principal_seconds."""
    twp = 100 * SECONDS_PER_YEAR  # 100 LINK staked for one full year
    apy = compute_realized_apy(rewards_link=5, time_weighted_principal_link_seconds=twp)
    assert isinstance(apy, float)
    assert abs(apy - 0.05) < 1e-9  # 5% APY


def test_compute_realized_apy_zero_principal_returns_zero() -> None:
    """Per docstring: zero denominator -> 0.0 (no NaN)."""
    assert compute_realized_apy(rewards_link=100, time_weighted_principal_link_seconds=0) == 0.0
    assert compute_realized_apy(rewards_link=100, time_weighted_principal_link_seconds=-5) == 0.0


def test_compute_apy_for_pool_returns_apy_data_point() -> None:
    """Return type matches type hint; realized APY ~5%."""
    stakes = [{"principal": 100, "start_unix": 0, "end_unix": SECONDS_PER_YEAR}]
    rewards = [{"amount_link": 5, "ts_unix": SECONDS_PER_YEAR // 2}]
    pt = compute_apy_for_pool(
        pool_address="0xABCD" + "0" * 36,
        snapshot_date="2026-05-11",
        snapshot_unix=SECONDS_PER_YEAR,
        stake_events=stakes,
        reward_events=rewards,
    )
    assert isinstance(pt, APYDataPoint)
    assert pt.pool_address == ("0xabcd" + "0" * 36)  # lowercased
    assert pt.cumulative_rewards_link == 5
    assert abs(pt.realized_apy - 0.05) < 1e-9


def test_compute_apy_for_pool_filters_rewards_by_snapshot() -> None:
    """Rewards after `snapshot_unix` are excluded from `cumulative_rewards_link`."""
    stakes = [{"principal": 100, "start_unix": 0, "end_unix": 100}]
    rewards = [
        {"amount_link": 10, "ts_unix": 50},
        {"amount_link": 99, "ts_unix": 1000},  # after snapshot
    ]
    pt = compute_apy_for_pool(
        pool_address="0x" + "a" * 40,
        snapshot_date="d",
        snapshot_unix=100,
        stake_events=stakes,
        reward_events=rewards,
    )
    assert pt.cumulative_rewards_link == 10


# --- reward_distribution --------------------------------------------------


def test_compute_distribution_efficiency_basic() -> None:
    distributed = [{"amount_link": 100}]
    claimed = [{"amount_link": 30}]
    eff = compute_distribution_efficiency(
        pool_address="0xABC" + "0" * 37,
        snapshot_date="2026-05-11",
        distributed_events=distributed,
        claimed_events=claimed,
    )
    assert isinstance(eff, DistributionEfficiency)
    assert eff.rewards_distributed == 100
    assert eff.rewards_claimed == 30
    assert abs(eff.claim_ratio - 0.3) < 1e-9
    assert eff.pool_address == ("0xabc" + "0" * 37)


def test_compute_distribution_efficiency_zero_distributed_no_div_zero() -> None:
    """Zero denominator returns claim_ratio = 0.0."""
    eff = compute_distribution_efficiency(
        pool_address="0x" + "0" * 40,
        snapshot_date="d",
        distributed_events=[],
        claimed_events=[],
    )
    assert eff.claim_ratio == 0.0


def test_compute_unclaimed_reward_balance() -> None:
    distributed = [{"amount_link": 100}, {"amount_link": 50}]
    claimed = [{"amount_link": 30}]
    balance = compute_unclaimed_reward_balance(distributed, claimed)
    assert isinstance(balance, int)
    assert balance == 120


# --- pa_fee_attribution ---------------------------------------------------


def test_classify_service_known_address() -> None:
    """A known service address maps to the service bucket."""
    # Pick a known address from the constant map and assert classification.
    for addr, expected in KNOWN_SERVICE_ADDRESSES.items():
        assert classify_service(addr) == expected
    # Mixed case should still match (lowercased internally).
    if KNOWN_SERVICE_ADDRESSES:
        sample = next(iter(KNOWN_SERVICE_ADDRESSES))
        assert classify_service(sample.upper()) == KNOWN_SERVICE_ADDRESSES[sample]


def test_classify_service_unknown_address_returns_other() -> None:
    assert classify_service("0x" + "0" * 40) == "other"
    assert classify_service("0xdeadbeef" + "0" * 32) == "other"


def test_attribute_pa_fees_groups_by_service_and_source() -> None:
    """One FeeAttribution per (service, source_address), sorted by inflow desc."""
    vrf = next(a for a, s in KNOWN_SERVICE_ADDRESSES.items() if s == "vrf")
    actions = [
        {"counterparty": vrf, "output_amount": 100},
        {"counterparty": vrf, "output_amount": 50},  # same source: sums to 150
        {"counterparty": "0x" + "f" * 40, "output_amount": 200},  # other
        {"counterparty": "", "output_amount": 99},  # skipped (no counterparty)
    ]
    out = attribute_pa_fees(actions, snapshot_date="2026-05-11")
    assert all(isinstance(o, FeeAttribution) for o in out)
    assert len(out) == 2  # two unique (service, source) keys
    # Sorted by inflow desc
    assert out[0].inflow_link >= out[1].inflow_link
    # The vrf source sums to 150
    vrf_rows = [o for o in out if o.service == "vrf"]
    assert len(vrf_rows) == 1
    assert vrf_rows[0].inflow_link == 150
    # The unknown source maps to "other"
    other_rows = [o for o in out if o.service == "other"]
    assert len(other_rows) == 1
    assert other_rows[0].inflow_link == 200
