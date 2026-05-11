"""public-function coverage for
`protocols/payment_abstraction/reserves_resolver.py`.
"""

from __future__ import annotations

from decoder.types import RawTrace, TraceTokenCall
from protocols.payment_abstraction.reserves_resolver import (
    LINK_TOKEN_ADDRESS,
    ReservesInflow,
    aggregate_reserves_inflows_per_tx,
    enrich_inflow_with_path,
    resolve_fee_aggregator_implementation,
    resolve_reserves_inflows_from_traces,
)
from protocols.payment_abstraction.semantics import PA_RESERVES_ADDRESS, PA_SWAP_AUTOMATOR_ADDRESS


def _trace_call(
    to_addr: str = PA_RESERVES_ADDRESS,
    token: str = LINK_TOKEN_ADDRESS,
    amount: int = 100,
) -> TraceTokenCall:
    return TraceTokenCall(
        raw_trace_call_id="rt",
        chain_id=1,
        block_number=24_139_066,
        tx_hash="0x" + "f" * 64,
        trace_address=[0, 0],
        token_address=token,
        method_name="transfer",
        from_addr=PA_SWAP_AUTOMATOR_ADDRESS,
        to_addr=to_addr,
        amount=amount,
    )


def test_resolve_reserves_inflows_picks_only_link_to_reserves() -> None:
    """LINK transfer to Reserves -> kept; other token / other recipient -> dropped."""
    keep = _trace_call()
    other_token = _trace_call(token="0x" + "11" * 20)
    other_to = _trace_call(to_addr="0x" + "22" * 20)
    inflows = resolve_reserves_inflows_from_traces([keep, other_token, other_to])
    assert all(isinstance(i, ReservesInflow) for i in inflows)
    assert len(inflows) == 1
    assert inflows[0].amount == 100
    assert inflows[0].sender == PA_SWAP_AUTOMATOR_ADDRESS
    assert inflows[0].source == "trace"


def test_enrich_inflow_with_path_walks_addresses() -> None:
    """Walking down a trace tree records the to_address of every successful
    intermediate call along the path to the leaf."""
    leaf = RawTrace(
        chain_id=1,
        block_number=24_139_066,
        tx_hash="0xt",
        type="CALL",
        from_addr=PA_SWAP_AUTOMATOR_ADDRESS,
        to_addr=LINK_TOKEN_ADDRESS,
        value=0,
        gas=0,
        gas_used=0,
        input_data="0x",
        output="0x",
        error=None,
        revert_reason=None,
        calls=[],
        trace_address=[0, 0],
    )
    middle = RawTrace(
        chain_id=1,
        block_number=24_139_066,
        tx_hash="0xt",
        type="CALL",
        from_addr="0x" + "ab" * 20,
        to_addr=PA_SWAP_AUTOMATOR_ADDRESS,
        value=0,
        gas=0,
        gas_used=0,
        input_data="0x",
        output="0x",
        error=None,
        revert_reason=None,
        calls=[leaf],
        trace_address=[0],
    )
    root = RawTrace(
        chain_id=1,
        block_number=24_139_066,
        tx_hash="0xt",
        type="CALL",
        from_addr="0x" + "cd" * 20,
        to_addr="0x" + "ee" * 20,
        value=0,
        gas=0,
        gas_used=0,
        input_data="0x",
        output="0x",
        error=None,
        revert_reason=None,
        calls=[middle],
        trace_address=[],
    )
    inflow = ReservesInflow(
        tx_hash="0xt",
        block_number=24_139_066,
        amount=100,
        sender=PA_SWAP_AUTOMATOR_ADDRESS,
        path=[],
        source="trace",
    )
    enriched = enrich_inflow_with_path(inflow, root, [0, 0])
    assert isinstance(enriched, ReservesInflow)
    assert enriched.path == [PA_SWAP_AUTOMATOR_ADDRESS, LINK_TOKEN_ADDRESS]
    # Original is not mutated.
    assert inflow.path == []


def test_resolve_fee_aggregator_implementation_returns_lowercase() -> None:
    """If the YAML phase has implementation_address -> return lowercase."""
    out = resolve_fee_aggregator_implementation(
        {
            "abi_version": "v1",
            "from_block": 0,
            "to_block": None,
            "implementation_address": "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        }
    )
    assert out == "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


def test_resolve_fee_aggregator_implementation_returns_none_when_absent() -> None:
    assert resolve_fee_aggregator_implementation({"abi_version": "v1"}) is None


def test_aggregate_reserves_inflows_per_tx_sums_amounts() -> None:
    """Multiple inflows in the same tx sum into one entry."""
    a = ReservesInflow(
        tx_hash="0xt1", block_number=1, amount=100, sender="x", path=[], source="trace"
    )
    b = ReservesInflow(
        tx_hash="0xt1", block_number=1, amount=50, sender="x", path=[], source="trace"
    )
    c = ReservesInflow(
        tx_hash="0xt2", block_number=2, amount=200, sender="y", path=[], source="trace"
    )
    out = aggregate_reserves_inflows_per_tx([a, b, c])
    assert isinstance(out, dict)
    assert out["0xt1"] == 150
    assert out["0xt2"] == 200
