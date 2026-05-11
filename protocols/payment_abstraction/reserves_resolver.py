"""Reserves balance resolution: walk the trace tree to find every internal
LINK transfer that lands at the Reserves contract, regardless of whether a
top-level Transfer event was emitted.

The PA Reserves contract sometimes receives LINK via multiple hops (e.g.,
SwapAutomator → DEX router → SwapAutomator → Reserves). The intermediate
hops may not emit Transfer events; surfacing them requires walking the trace.

This resolver also reads the EIP-1967 implementation slot of FeeAggregator
(if it's a proxy) so the decoder can locate the active ABI.

Reference constants:
    LINK token address (mainnet): 0x514910771af9ca656af840dff83e8264ecf986ca
    PA Reserves address:          0x5680681ed3767b96914ce741a308155c7fb9171d
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from decoder.proxy_resolver import (
    EIP1967_IMPL_SLOT,
    resolve_implementation_from_config,
)
from decoder.types import RawTrace, TraceTokenCall
from protocols.payment_abstraction.semantics import PA_RESERVES_ADDRESS

LINK_TOKEN_ADDRESS = "0x514910771af9ca656af840dff83e8264ecf986ca"


@dataclass(frozen=True)
class ReservesInflow:
    """One LINK movement landing at the Reserves contract within a tx.

    Attributes:
        tx_hash:        the transaction containing the inflow
        amount:         raw uint256 LINK amount
        sender:         the immediate caller that transferred LINK in
        path:           the upstream addresses (de-duplicated) on the trace
                        path leading to this inflow
        source:         "log" if a Transfer log evidenced this, else "trace"
    """

    tx_hash: str
    block_number: int
    amount: int
    sender: str
    path: list[str]
    source: str  # "log" | "trace"


def resolve_reserves_inflows_from_traces(
    trace_calls: Iterable[TraceTokenCall],
) -> list[ReservesInflow]:
    """Filter trace-derived ERC-20 transfer calls down to those whose `to_addr`
    equals the Reserves contract. Each match becomes a ReservesInflow.

    The `path` field is left empty here; it is populated by
    `enrich_inflow_with_path` when the caller has access to the full trace
    tree.
    """
    out: list[ReservesInflow] = []
    target = PA_RESERVES_ADDRESS.lower()
    for c in trace_calls:
        if c.token_address.lower() != LINK_TOKEN_ADDRESS:
            continue
        if c.to_addr.lower() != target:
            continue
        out.append(
            ReservesInflow(
                tx_hash=c.tx_hash,
                block_number=c.block_number,
                amount=c.amount,
                sender=c.from_addr,
                path=[],
                source="trace",
            )
        )
    return out


def enrich_inflow_with_path(
    inflow: ReservesInflow,
    root: RawTrace,
    leaf_trace_address: list[int],
) -> ReservesInflow:
    """Walk from the root of the trace tree down to the leaf and record the
    `to_address` of every successful intermediate call. Used by
    `docs/protocol-validation.md` to demonstrate the multi-hop fee path.

    Returns a new ReservesInflow; does not mutate the input.
    """
    path: list[str] = []
    node = root
    for idx in leaf_trace_address:
        if idx >= len(node.calls):
            break
        node = node.calls[idx]
        if node.to_addr is not None:
            addr = node.to_addr.lower()
            if not path or path[-1] != addr:
                path.append(addr)
    return ReservesInflow(
        tx_hash=inflow.tx_hash,
        block_number=inflow.block_number,
        amount=inflow.amount,
        sender=inflow.sender,
        path=path,
        source=inflow.source,
    )


def resolve_fee_aggregator_implementation(
    fee_aggregator_phase_yaml: dict[str, object],
) -> str | None:
    """Locate the active implementation address for the FeeAggregator proxy
    from the contracts YAML phase definition. Returns lowercase address or
    None if the proxy is not modelled as such (i.e., logical contract is the
    same as the on-chain address).

    Internally references EIP1967_IMPL_SLOT for documentation symmetry — the
    proxy_resolver module is the source of truth for the slot constant.
    """
    _ = EIP1967_IMPL_SLOT  # documented; consumed by the rpc fallback path
    from decoder.types import Phase

    to_block_value = fee_aggregator_phase_yaml.get("to_block")
    phase = Phase(
        contract_address="",
        abi_version=str(fee_aggregator_phase_yaml.get("abi_version", "")),
        from_block=int(str(fee_aggregator_phase_yaml.get("from_block", 0))),
        to_block=int(str(to_block_value)) if to_block_value is not None else None,
    )
    return resolve_implementation_from_config(phase, fee_aggregator_phase_yaml)


def aggregate_reserves_inflows_per_tx(
    inflows: list[ReservesInflow],
) -> dict[str, int]:
    """Sum reserves inflow amounts per tx — useful for the analytics layer's
    per-tx reserve accumulation question."""
    out: dict[str, int] = {}
    for f in inflows:
        out[f.tx_hash] = out.get(f.tx_hash, 0) + f.amount
    return out
