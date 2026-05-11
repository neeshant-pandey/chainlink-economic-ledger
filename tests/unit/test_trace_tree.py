"""trace tree reconstruction tests.

Given flat rows with `trace_address` values "", "0", "1", "0,0", "0,1",
"1,0", asserts:
  - Resulting tree has exactly one root (trace_address [])
  - Root has 2 children ([0] and [1]) in sibling order
  - Node [0] has 2 children ([0,0], [0,1]) in order
  - `trace_address` parsed to `list[int]` for `RawTrace.trace_address`
  - Reverse: tree → flat preserves all rows
"""

from __future__ import annotations

from decoder.trace_tree import (
    build_call_tree,
    flatten_call_tree,
    parse_trace_address,
    serialize_trace_address,
)
from decoder.types import RawTrace


def _row(trace_addr: str, to_addr: str = "0xabc") -> dict[str, object]:
    return {
        "transaction_hash": "0xtx",
        "block_number": 1,
        "trace_address": trace_addr,
        "call_type": "call",
        "from_address": "0xfrom",
        "to_address": to_addr,
        "value": "0",
        "gas": 21000,
        "gas_used": 1000,
        "input": "0x",
        "output": "0x",
        "error": None,
        "status": 1,
        "subtraces": 0,
    }


def test_parse_trace_address_empty_to_root() -> None:
    assert parse_trace_address("") == []
    assert parse_trace_address(None) == []


def test_parse_trace_address_singleton() -> None:
    assert parse_trace_address("0") == [0]
    assert parse_trace_address("5") == [5]


def test_parse_trace_address_multi() -> None:
    assert parse_trace_address("0,2,1") == [0, 2, 1]
    assert parse_trace_address("10,20,30") == [10, 20, 30]


def test_serialize_inverse_of_parse() -> None:
    for s in ["", "0", "5", "0,1", "0,2,1"]:
        assert serialize_trace_address(parse_trace_address(s)) == s


def test_build_call_tree_simple() -> None:
    rows = [_row(s) for s in ["", "0", "1", "0,0", "0,1", "1,0"]]
    root = build_call_tree(rows, chain_id=1)

    assert isinstance(root, RawTrace)
    assert root.trace_address == []
    assert len(root.calls) == 2
    # sibling order: child 0 first, then child 1
    assert root.calls[0].trace_address == [0]
    assert root.calls[1].trace_address == [1]
    # node "0" has two children: [0,0] and [0,1]
    node_0 = root.calls[0]
    assert len(node_0.calls) == 2
    assert node_0.calls[0].trace_address == [0, 0]
    assert node_0.calls[1].trace_address == [0, 1]
    # node "1" has 1 child
    node_1 = root.calls[1]
    assert len(node_1.calls) == 1
    assert node_1.calls[0].trace_address == [1, 0]


def test_trace_address_is_list_of_int() -> None:
    rows = [_row(""), _row("0"), _row("0,2"), _row("0,2,1")]
    root = build_call_tree(rows, chain_id=1)

    def _check(node: RawTrace) -> None:
        assert isinstance(node.trace_address, list)
        for x in node.trace_address:
            assert isinstance(x, int)
        for child in node.calls:
            _check(child)

    _check(root)


def test_flatten_inverse_of_build() -> None:
    rows = [_row(s) for s in ["", "0", "1", "0,0", "0,1", "1,0"]]
    root = build_call_tree(rows, chain_id=1)
    flat = flatten_call_tree(root)
    addresses = {serialize_trace_address(t.trace_address) for t in flat}
    assert addresses == {"", "0", "1", "0,0", "0,1", "1,0"}
    assert len(flat) == len(rows)


def test_build_call_tree_rejects_missing_parent() -> None:
    """A row with trace_address "0,1" but no row for "0" → ValueError."""
    import pytest

    rows = [_row(""), _row("0,1")]  # missing "0"
    with pytest.raises(ValueError):
        build_call_tree(rows, chain_id=1)


def test_build_call_tree_rejects_multiple_roots() -> None:
    import pytest

    rows = [_row(""), _row("")]
    with pytest.raises(ValueError):
        build_call_tree(rows, chain_id=1)
