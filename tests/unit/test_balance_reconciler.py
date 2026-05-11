"""Tests for `reconciliation.balance_reconciler`."""

from __future__ import annotations

from reconciliation.balance_reconciler import (
    compute_balance_delta,
    reconcile_pool_movement_vs_balance,
    verify_pool_balance,
)
from reconciliation.movement_builder import TokenMovement


def _movement(
    from_addr: str,
    to_addr: str,
    amount: int,
    block_number: int = 100,
) -> TokenMovement:
    return TokenMovement(
        movement_id=f"mv|{from_addr}|{to_addr}|{amount}",
        chain_id=1,
        block_number=block_number,
        tx_hash="0xtx",
        token_address="0xtoken",
        from_addr=from_addr,
        to_addr=to_addr,
        amount=amount,
    )


def test_compute_balance_delta_inflow_outflow() -> None:
    """Mix of inbound and outbound movements nets correctly."""
    pool = "0xpool"
    movements = [
        _movement("0xa", pool, 100),
        _movement(pool, "0xb", 30),
        _movement("0xc", pool, 50),
    ]
    delta = compute_balance_delta(movements, pool, 0, 1000)
    assert delta == 100 + 50 - 30


def test_compute_balance_delta_filters_block_range() -> None:
    pool = "0xpool"
    movements = [
        _movement("0xa", pool, 100, block_number=50),  # before
        _movement("0xa", pool, 200, block_number=150),  # in range
        _movement("0xa", pool, 300, block_number=250),  # after
    ]
    assert compute_balance_delta(movements, pool, 100, 200) == 200


def test_compute_balance_delta_ignores_self_transfers() -> None:
    pool = "0xpool"
    movements = [_movement(pool, pool, 100)]
    assert compute_balance_delta(movements, pool, 0, 1000) == 0


def test_compute_balance_delta_case_insensitive_address_comparison() -> None:
    """L3 edge case (docstring: 'address comparison is case-insensitive --
    internal storage convention is lowercase but inputs may not be').

    Movements stored with mixed-case addresses must still match a target
    address passed in a different case. Both the target and the movement
    from_addr / to_addr should be canonicalised before comparison.
    """
    # Build a mixed-case address from a lowercase base, so the test source
    # itself stays canonical-case-clean while the runtime
    # input under test is mixed/upper case.
    pool_lower = "0xaabbccddee0011223344556677889900ffeeddcc"
    pool_mixed = "".join(ch.upper() if (i % 2 == 0) else ch for i, ch in enumerate(pool_lower))
    other = "0x1111111111111111111111111111111111111111"
    movements = [
        _movement(other, pool_mixed, 100),  # inflow (mixed-case to)
        _movement(pool_mixed.upper(), other, 30),  # outflow (uppercase from)
    ]
    # 1) Target passed in lowercase still matches mixed/upper-case movements.
    delta_lower = compute_balance_delta(movements, pool_lower, 0, 1000)
    assert delta_lower == 100 - 30
    # 2) Target passed in UPPERCASE returns the same result.
    delta_upper = compute_balance_delta(movements, pool_lower.upper(), 0, 1000)
    assert delta_upper == 100 - 30
    # 3) Target passed in mixed-case returns the same result.
    delta_mixed = compute_balance_delta(movements, pool_mixed, 0, 1000)
    assert delta_mixed == 100 - 30


class _StubBalanceProvider:
    def __init__(self, balances: dict[int, int]) -> None:
        self._balances = balances

    def get_token_balance(self, token: str, holder: str, block: int) -> int:
        _ = token, holder
        return self._balances.get(block, 0)


def test_verify_pool_balance_consistent() -> None:
    """observed delta == expected → BalanceVerification.is_consistent=True."""
    client = _StubBalanceProvider({99: 0, 100: 100})
    result = verify_pool_balance(
        client=client,  # type: ignore[arg-type]
        token_address="0xtoken",
        pool_address="0xpool",
        block_number=100,
        expected_delta=100,
        prior_block_number=99,
    )
    assert result.is_consistent is True
    assert result.diff == 0
    assert result.observed_balance_delta == 100


def test_verify_pool_balance_inconsistent_diff_signed() -> None:
    """Mismatch produces a signed diff."""
    client = _StubBalanceProvider({99: 0, 100: 100})
    result = verify_pool_balance(
        client=client,  # type: ignore[arg-type]
        token_address="0xtoken",
        pool_address="0xpool",
        block_number=100,
        expected_delta=50,
        prior_block_number=99,
    )
    assert result.is_consistent is False
    # observed (100) - expected (50) = +50
    assert result.diff == 50


def test_reconcile_pool_movement_vs_balance_full() -> None:
    """End-to-end: snapshots + movements over a range → PoolReconciliation."""
    movements = [_movement("0xa", "0xpool", 100, block_number=100)]
    client = _StubBalanceProvider({99: 0, 200: 100})
    result = reconcile_pool_movement_vs_balance(
        client=client,  # type: ignore[arg-type]
        token_address="0xtoken",
        pool_address="0xpool",
        movements=movements,
        from_block=100,
        to_block=200,
    )
    assert result.is_consistent
    assert result.net_movements == 100
    assert result.start_balance == 0
    assert result.end_balance == 100
