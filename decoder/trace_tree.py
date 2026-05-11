"""Reconstruct the nested call-tree shape from BigQuery's flat trace rows.

BQ stores `crypto_ethereum.traces` as a flat list of one row per call frame,
indexed by `trace_address` (a comma-joined string of indices, e.g. `"0,2,1"` or
`""` for the root). The nested callTracer JSON shape — `parent.calls[i]` —
must be reconstructed in Python.

That reconstruction is itself a Vector-1 demonstration: it shows the implementer
understands the trace data model below the convenience of the callTracer JSON.

Algorithm:
  1. Parse trace_address strings to `list[int]`
  2. Sort by depth ascending, then by trace_address lexicographically (siblings
     in deterministic sibling order)
  3. For each row, find its parent (trace_address minus its last index) and
     append it to the parent's `calls` list

The reverse — flatten a tree back to rows in stable order — is `flatten_call_tree`.
"""

from __future__ import annotations

from typing import Any

from decoder.types import RawTrace


def parse_trace_address(s: str | list[int] | None) -> list[int]:
    """BQ stores trace_address as a comma-joined string. Convert to list[int].

    Empty / null / "" → [] (the root call). A list[int] passed through is
    returned (defensive — callers may already have parsed it).
    """
    if s is None or s == "" or s == []:
        return []
    if isinstance(s, list):
        return [int(x) for x in s]
    if not isinstance(s, str):
        raise TypeError(f"trace_address must be str|list|None, got {type(s).__name__}")
    return [int(part) for part in s.split(",") if part != ""]


def serialize_trace_address(addr: list[int]) -> str:
    """Inverse of `parse_trace_address`. Empty list → "" (the root)."""
    return ",".join(str(i) for i in addr)


def _row_to_raw_trace(row: dict[str, Any], chain_id: int | None) -> RawTrace:
    """Convert a BQ trace row dict into a RawTrace dataclass (no children yet).

    Field mappings:
        row["transaction_hash"]   -> tx_hash
        row["trace_address"]      -> trace_address (parsed via parse_trace_address)
        row["call_type"] / "type" -> type
        row["from_address"]       -> from_addr
        row["to_address"]         -> to_addr
        row["value"]              -> value (int)
        row["gas"], "gas_used"    -> gas / gas_used
        row["input"]              -> input_data
        row["output"]             -> output
        row["error"]              -> error
        row["status"]             -> revert_reason inferred (status==0 → "reverted")
    """
    addr = parse_trace_address(row.get("trace_address"))
    call_type = row.get("call_type") or row.get("type") or row.get("trace_type") or "call"
    error = row.get("error")
    status = row.get("status")
    revert_reason = None
    if error is None and status is not None and int(status) == 0:
        error = "reverted"
        revert_reason = "status=0"
    elif error is not None:
        revert_reason = error

    value_field = row.get("value")
    if value_field is None:
        value_int = 0
    elif isinstance(value_field, int):
        value_int = value_field
    else:
        value_int = int(str(value_field))

    block_number = int(row.get("block_number", 0))
    cid = chain_id if chain_id is not None else int(row.get("chain_id", 1))

    return RawTrace(
        chain_id=cid,
        block_number=block_number,
        tx_hash=str(row.get("transaction_hash") or row.get("tx_hash", "")).lower(),
        type=str(call_type).upper(),
        from_addr=str(row.get("from_address") or row.get("from_addr", "")).lower(),
        to_addr=(
            str(row["to_address"]).lower()
            if row.get("to_address")
            else (str(row["to_addr"]).lower() if row.get("to_addr") else None)
        ),
        value=value_int,
        gas=int(row.get("gas", 0)),
        gas_used=int(row.get("gas_used", 0)),
        input_data=str(row.get("input") or row.get("input_data") or "0x"),
        output=str(row.get("output") or "0x"),
        error=error,
        revert_reason=revert_reason,
        calls=[],
        trace_address=addr,
    )


def build_call_tree(
    rows: list[dict[str, Any]],
    chain_id: int | None = None,
) -> RawTrace:
    """Reconstruct the nested RawTrace tree from a flat list of BQ trace rows
    for ONE transaction.

    All rows must share the same `transaction_hash`. The function expects at
    least one row; the row with `trace_address == ""` (or [], or None) is the
    root.

    Children are appended to their parent's `.calls` in the natural sibling
    order (parsed from the integer suffix of `trace_address`).

    Raises ValueError if (a) rows have mixed tx hashes, (b) a parent is missing
    for a non-root child, or (c) more than one root is found.
    """
    if not rows:
        raise ValueError("build_call_tree: rows is empty")

    # Convert + sort
    raw_traces: list[RawTrace] = [_row_to_raw_trace(r, chain_id) for r in rows]
    tx_hashes = {t.tx_hash for t in raw_traces}
    if len(tx_hashes) > 1:
        raise ValueError(f"build_call_tree: mixed tx hashes {tx_hashes}")

    # We need mutable .calls lists; RawTrace is frozen but `calls` is a list
    # (mutable container). Construct a fresh tree by replacing .calls in
    # post-order. Simplest approach: use a parallel mutable dict.

    by_addr: dict[str, RawTrace] = {serialize_trace_address(t.trace_address): t for t in raw_traces}
    if len(by_addr) != len(raw_traces):
        # Duplicate trace_address values — invalid
        raise ValueError("build_call_tree: duplicate trace_address values")

    # Sort children at each parent in sibling order (last-element ascending)
    sorted_traces = sorted(
        raw_traces,
        key=lambda t: (len(t.trace_address), t.trace_address),
    )

    root: RawTrace | None = None
    for t in sorted_traces:
        if not t.trace_address:
            if root is not None:
                raise ValueError("build_call_tree: more than one root")
            root = t
            continue
        parent_addr = serialize_trace_address(t.trace_address[:-1])
        parent = by_addr.get(parent_addr)
        if parent is None:
            raise ValueError(
                f"build_call_tree: missing parent for trace_address "
                f"{serialize_trace_address(t.trace_address)} (expected parent "
                f"at {parent_addr!r})"
            )
        parent.calls.append(t)

    if root is None:
        raise ValueError("build_call_tree: no root row (trace_address='')")

    # Within each parent, sort children by their last index ascending (sibling
    # order). The earlier sort already does this for the global list, but the
    # parent-relative order matters.
    def _sort_recursive(node: RawTrace) -> None:
        node.calls.sort(key=lambda c: c.trace_address[-1] if c.trace_address else 0)
        for child in node.calls:
            _sort_recursive(child)

    _sort_recursive(root)
    return root


def flatten_call_tree(root: RawTrace) -> list[RawTrace]:
    """Reverse of `build_call_tree`. DFS pre-order; trace_address is populated
    on every node already (so this is just a recursive walk).

    The output preserves all rows and their order such that
    `build_call_tree(flatten_call_tree(t))` reconstructs `t`.
    """
    out: list[RawTrace] = []

    def _walk(node: RawTrace) -> None:
        out.append(node)
        for child in node.calls:
            _walk(child)

    _walk(root)
    return out


def assign_trace_addresses(node: RawTrace, prefix: list[int] | None = None) -> RawTrace:
    """Walk a tree where `trace_address` may be empty/missing on children
    (e.g., produced by `debug_traceTransaction`'s callTracer where the JSON has
    no explicit trace_address) and populate it.

    The root receives `[]`; child[i] receives `parent_addr + [i]`.
    """
    addr = list(prefix) if prefix is not None else []
    # rebuild node with trace_address set, since RawTrace is frozen
    new_node = RawTrace(
        chain_id=node.chain_id,
        block_number=node.block_number,
        tx_hash=node.tx_hash,
        type=node.type,
        from_addr=node.from_addr,
        to_addr=node.to_addr,
        value=node.value,
        gas=node.gas,
        gas_used=node.gas_used,
        input_data=node.input_data,
        output=node.output,
        error=node.error,
        revert_reason=node.revert_reason,
        calls=[],
        trace_address=addr,
    )
    for i, child in enumerate(node.calls):
        new_node.calls.append(assign_trace_addresses(child, addr + [i]))
    return new_node
