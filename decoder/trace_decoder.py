"""Decode the recursive trace tree (the output of `debug_traceTransaction` with
`callTracer`, OR the reconstructed tree produced by `trace_tree.build_call_tree`
from BQ's flat trace rows).

Walks the call graph and emits DecodedCall records. ERC-20 transfer extraction
is in `extract_erc20_transfer_calls` and intentionally filters reverted calls —
see the `TraceTokenCall` evidence used by `reconciliation/movement_builder`.

A movement is emitted only when:
  - `call.success`
  - `parent_success` (every ancestor on the trace_address path succeeded)
  - `receipts_by_tx[tx_hash].status == 1` (the top-level tx succeeded)

ERC-20 selectors used:
    transfer(address,uint256)              0xa9059cbb
    transferFrom(address,address,uint256)  0x23b872dd
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from decoder.abi_registry import AbiRegistry
from decoder.calldata_decoder import (
    ERC20_TRANSFER_FROM_SELECTOR,
    ERC20_TRANSFER_SELECTOR,
    decode_erc20_transfer_calldata,
    extract_method_selector,
)
from decoder.types import DecodedCall, RawTrace, Receipt, TraceTokenCall

type CallPredicate = Callable[[RawTrace], bool]


def compute_raw_trace_call_id(tx_hash: str, trace_address: list[int]) -> str:
    """SHA-256 of `(tx_hash, trace_address)`. Trace address [0,2,1] means
    `root.calls[0].calls[2].calls[1]` — uniquely identifies any call within the tx.
    The empty list (root call) encodes as "" so root cannot collide with [0].
    """
    addr_str = ",".join(str(i) for i in trace_address)
    canonical = f"raw_trace_call|{tx_hash.lower()}|{addr_str}"
    return hashlib.sha256(canonical.encode()).hexdigest()


def decode_trace_calls(trace: RawTrace, registry: AbiRegistry) -> list[DecodedCall]:
    """Recursively decodes every node in the call tree. Each output carries
    `success` (this call) and `parent_success` (every ancestor succeeded).

    `trace.trace_address` is expected to be populated already (the root has
    [], children have [0], [1], ..., grandchildren have [0,0], [0,1], ...).

    Returns a flat list in DFS / pre-order; for any node, its ancestors appear
    earlier in the list.
    """
    out: list[DecodedCall] = []

    def _walk(node: RawTrace, parent_success: bool) -> None:
        # node-level success: error is None AND no revert reason
        node_success = node.error is None and node.revert_reason is None
        method_name = "<unknown>"
        method_selector = extract_method_selector(node.input_data or "0x")
        params: dict[str, object] = {}

        # Try to resolve via registry — if the contract is registered, we can
        # decode arguments. Otherwise leave params empty (it's still useful to
        # have the selector for the recon layer).
        if node.to_addr is not None:
            try:
                abi = registry.get(node.to_addr.lower(), node.block_number)
                # Find the function whose selector matches
                from decoder.calldata_decoder import _find_method_by_selector

                method = _find_method_by_selector(abi, method_selector)
                if method is not None:
                    method_name = method.get("name", "<unnamed>")
                    # Try to decode params; on failure leave empty
                    from decoder.calldata_decoder import decode_calldata

                    res = decode_calldata(node.input_data or "0x", abi)
                    if res.success and res.decoded is not None:
                        decoded_call = res.decoded
                        # decoded_call is a DecodedCall (calldata path)
                        if hasattr(decoded_call, "params"):
                            params = decoded_call.params
            except KeyError:
                pass

        # Fast-path ERC-20 selector recognition for any contract
        if method_name == "<unknown>":
            erc20 = decode_erc20_transfer_calldata(node.input_data or "0x")
            if erc20 is not None:
                method_name = erc20["method"]
                params = {k: v for k, v in erc20.items() if k not in ("method",) and v is not None}

        decoded = DecodedCall(
            raw_trace_call_id=compute_raw_trace_call_id(node.tx_hash, list(node.trace_address)),
            chain_id=node.chain_id,
            block_number=node.block_number,
            tx_hash=node.tx_hash.lower(),
            trace_address=list(node.trace_address),
            contract_address=node.to_addr.lower() if node.to_addr else None,
            method_name=method_name,
            method_selector=method_selector,
            params=params,
            success=node_success,
            parent_success=parent_success,
        )
        out.append(decoded)
        for child in node.calls:
            _walk(child, parent_success and node_success)

    _walk(trace, parent_success=True)
    return out


def walk_trace(trace: RawTrace, predicate: CallPredicate) -> list[RawTrace]:
    """DFS over the call tree, returns every node where `predicate(node)` is
    True. `trace_address` is populated on each returned node (assumed already
    set by the caller / by `trace_tree.build_call_tree`).
    """
    out: list[RawTrace] = []

    def _walk(node: RawTrace) -> None:
        if predicate(node):
            out.append(node)
        for child in node.calls:
            _walk(child)

    _walk(trace)
    return out


def extract_erc20_transfer_calls(
    decoded_calls: list[DecodedCall],
    token_address: str,
    receipts_by_tx: dict[str, Receipt],
) -> list[TraceTokenCall]:
    """Filters decoded calls down to successful internal `transfer` /
    `transferFrom` invocations on `token_address`.

    A call is included only if ALL of:
      - call.contract_address == token_address (case-insensitive)
      - call.method_name in {"transfer", "transferFrom"}
      - call.method_selector in {0xa9059cbb, 0x23b872dd}
      - call.success is True
      - call.parent_success is True (no ancestor reverted; the trace-success invariant)
      - receipts_by_tx[call.tx_hash].status == 1 (top-level tx succeeded)

    Note : a failed top-level tx contributes ZERO movements even
    if the trace tree shows successful sub-calls. Likewise, a successful call
    whose grandparent reverted contributes zero — the descendant's effects are
    rolled back.
    """
    target_token = token_address.lower()
    out: list[TraceTokenCall] = []
    for call in decoded_calls:
        if call.contract_address is None:
            continue
        if call.contract_address.lower() != target_token:
            continue
        # Accept by name OR by selector — skip only if both fail to match.
        if call.method_name not in ("transfer", "transferFrom") and call.method_selector not in (
            ERC20_TRANSFER_SELECTOR,
            ERC20_TRANSFER_FROM_SELECTOR,
        ):
            continue
        if not call.success or not call.parent_success:
            continue
        receipt = receipts_by_tx.get(call.tx_hash.lower())
        if receipt is None or receipt.status != 1:
            continue

        # Resolve from / to / amount from params
        params = call.params or {}
        if call.method_selector == ERC20_TRANSFER_SELECTOR or call.method_name == "transfer":
            # transfer(to, amount) — `from` is the trace frame's caller (we
            # don't have it on DecodedCall directly; recon layer joins it from
            # the raw trace frame). For movement IDs we use what we have.
            method_literal = "transfer"
            from_addr = str(params.get("from", "")).lower() or ""
            to_addr = str(params.get("to", "")).lower()
            amount = int(params.get("amount", params.get("value", 0)))
        else:
            method_literal = "transferFrom"
            from_addr = str(params.get("from", "")).lower()
            to_addr = str(params.get("to", "")).lower()
            amount = int(params.get("amount", params.get("value", 0)))

        out.append(
            TraceTokenCall(
                raw_trace_call_id=call.raw_trace_call_id,
                chain_id=call.chain_id,
                block_number=call.block_number,
                tx_hash=call.tx_hash,
                trace_address=list(call.trace_address),
                token_address=target_token,
                method_name=method_literal,  # type: ignore[arg-type]
                from_addr=from_addr,
                to_addr=to_addr,
                amount=amount,
            )
        )
    return out
