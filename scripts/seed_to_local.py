#!/usr/bin/env python3
"""Run the REAL decode pipeline over the REAL golden fixtures and dump the
output of every layer as CSV seeds for the dbt `local` (DuckDB) target.

This script is the bridge between the Python pipeline and the DuckDB-backed
end-to-end demo. It reads the same `tests/fixtures/golden_*` files the unit
tests load, walks them through:

    decoder.event_decoder        -> DecodedEvent rows
    decoder.trace_tree           -> nested trace tree
    decoder.trace_decoder        -> DecodedCall rows + TraceTokenCall extraction
    reconciliation.movement_builder
                                 -> log + trace TokenMovements (unified)
    protocols.staking_v02.semantics
                                 -> Staking EconomicAction rows
    protocols.payment_abstraction.semantics
                                 -> PA PAEconomicAction rows
    reconciliation.economic_reconciler
                                 -> N:M ActionMovementMatch edges
    protocols.staking_v02.ledger_builder + payment_abstraction.ledger_builder
                                 -> LedgerEntry rows

…and writes one CSV per dbt seed. All values come from the real fixture JSON.
The local demo is built from cached mainnet fixture data.

Usage:
    uv run python scripts/seed_to_local.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from decoder.abi_registry import AbiRegistry
from decoder.event_decoder import decode_log
from decoder.trace_decoder import (
    decode_trace_calls,
    extract_erc20_transfer_calls,
)
from decoder.trace_tree import build_call_tree
from decoder.types import Abi, RawLog, RawTrace, Receipt
from protocols.payment_abstraction.ledger_builder import (
    PADirection,
    build_pa_ledger_entries,
)
from protocols.payment_abstraction.semantics import (
    PA_FEE_AGGREGATOR_ADDRESS,
    PA_RESERVES_ADDRESS,
    PA_SWAP_AUTOMATOR_ADDRESS,
    PAActionKind,
    PAEconomicAction,
    classify_pa_event_as_action,
)
from protocols.staking_v02.ledger_builder import build_ledger_entries
from protocols.staking_v02.semantics import (
    EconomicAction,
    classify_event_as_action,
)
from reconciliation.economic_reconciler import (
    ActionMovementMatch,
    Status,
    match_action_to_movements,
)
from reconciliation.movement_builder import (
    TokenMovement,
    build_movements_from_trace_calls,
    build_movements_from_transfer_logs,
    unify_movements,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
SEED_DIR = PROJECT_ROOT / "dbt" / "seeds"

LINK = "0x514910771af9ca656af840dff83e8264ecf986ca"
COMMUNITY_POOL = "0xbc10f2e862ed4502144c7d632a3459f49dfcdb5e"
STAKED_TOPIC0 = "0xb4caaf29adda3eefee3ad552a8e85058589bf834c7466cae4ee58787f70589ed"
ASSET_TRANSFERRED_FOR_SWAP_TOPIC0 = (
    "0xc153544804f2cfae0e8eb92d3f202c159d0caf2f5590d790a987091dc85366a0"
)


# ---------------------------------------------------------------------------
# Fixture loaders (mirror the unit-test loaders so the same artifacts feed
# both pytest and the local dbt seeds — single source of truth).
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _load_tx(fixture: Path) -> dict[str, Any]:
    return _load_json(fixture / "tx.json")


def _load_block(fixture: Path) -> dict[str, Any]:
    return _load_json(fixture / "block.json")


def _load_receipt(fixture: Path) -> Receipt:
    r = _load_json(fixture / "receipt.json")
    return Receipt(
        chain_id=1,
        block_number=int(r["blockNumber"], 16),
        block_hash=r["blockHash"],
        tx_hash=r["transactionHash"],
        tx_index=int(r["transactionIndex"], 16),
        status=int(r["status"], 16),
        gas_used=int(r["gasUsed"], 16),
        effective_gas_price=int(r["effectiveGasPrice"], 16) if r.get("effectiveGasPrice") else None,
        cumulative_gas_used=int(r["cumulativeGasUsed"], 16),
        contract_address=r.get("contractAddress"),
        logs_count=len(r.get("logs", [])),
    )


def _load_logs(fixture: Path) -> list[RawLog]:
    raw_logs = _load_json(fixture / "logs.json")
    return [
        RawLog(
            chain_id=1,
            block_number=int(log["blockNumber"], 16),
            block_hash=log["blockHash"],
            tx_hash=log["transactionHash"],
            tx_index=int(log["transactionIndex"], 16),
            log_index=int(log["logIndex"], 16),
            address=log["address"].lower(),
            topics=log["topics"],
            data=log["data"],
        )
        for log in raw_logs
    ]


def _trace_node_to_flat_rows(
    node: dict[str, Any],
    tx_hash: str,
    block_number: int,
    chain_id: int = 1,
    trace_address: list[int] | None = None,
    parent_failed: bool = False,
) -> list[dict[str, Any]]:
    addr = list(trace_address) if trace_address is not None else []
    err = node.get("error")
    rows: list[dict[str, Any]] = [
        {
            "transaction_hash": tx_hash,
            "block_number": block_number,
            "chain_id": chain_id,
            "trace_address": ",".join(str(i) for i in addr),
            "call_type": (node.get("type") or "CALL").lower(),
            "from_address": (node.get("from") or "").lower(),
            "to_address": (node.get("to") or "").lower() if node.get("to") else None,
            "value": int(node.get("value", "0x0"), 16) if isinstance(node.get("value"), str) else 0,
            "gas": int(node.get("gas", "0x0"), 16) if isinstance(node.get("gas"), str) else 0,
            "gas_used": int(node.get("gasUsed", "0x0"), 16)
            if isinstance(node.get("gasUsed"), str)
            else 0,
            "input": node.get("input", "0x"),
            "output": node.get("output", "0x"),
            "error": err,
            "status": 0 if (err or parent_failed) else 1,
            "subtraces": len(node.get("calls", [])),
        }
    ]
    failed = parent_failed or err is not None
    for i, child in enumerate(node.get("calls", [])):
        rows.extend(
            _trace_node_to_flat_rows(child, tx_hash, block_number, chain_id, addr + [i], failed)
        )
    return rows


def _load_trace(fixture: Path) -> RawTrace:
    tx = _load_tx(fixture)
    node = _load_json(fixture / "trace.json")
    rows = _trace_node_to_flat_rows(
        node,
        tx_hash=tx["hash"].lower(),
        block_number=int(tx["blockNumber"], 16),
        chain_id=1,
    )
    return build_call_tree(rows, chain_id=1)


# ---------------------------------------------------------------------------
# Minimal in-memory ABIs sufficient for the two golden tx flows.
# ---------------------------------------------------------------------------


def _erc20_transfer_abi() -> Abi:
    return Abi(
        abi_version="erc20_v1",
        json_abi=[
            {
                "type": "event",
                "name": "Transfer",
                "anonymous": False,
                "inputs": [
                    {"name": "from", "type": "address", "indexed": True},
                    {"name": "to", "type": "address", "indexed": True},
                    {"name": "value", "type": "uint256", "indexed": False},
                ],
            }
        ],
    )


def _staking_pool_abi() -> Abi:
    return Abi(
        abi_version="staking_pool_v02",
        json_abi=[
            {
                "type": "event",
                "name": "Staked",
                "anonymous": False,
                "inputs": [
                    {"name": "staker", "type": "address", "indexed": True},
                    {"name": "amount", "type": "uint256", "indexed": False},
                    {"name": "newPrincipal", "type": "uint256", "indexed": False},
                    {"name": "totalPoolPrincipal", "type": "uint256", "indexed": False},
                ],
            }
        ],
    )


def _fee_aggregator_abi() -> Abi:
    return Abi(
        abi_version="pa_fee_aggregator_v1",
        json_abi=[
            {
                "type": "event",
                "name": "AssetTransferredForSwap",
                "anonymous": False,
                "inputs": [
                    {"name": "assetReceiver", "type": "address", "indexed": True},
                    {"name": "asset", "type": "address", "indexed": True},
                    {"name": "amount", "type": "uint256", "indexed": False},
                ],
            }
        ],
    )


# ---------------------------------------------------------------------------
# Stub ContractRegistry so semantics layer can resolve roles for our two
# specific contracts without loading the full YAML chain.
# ---------------------------------------------------------------------------


class _StubContractRegistry:
    """Just enough surface for `classify_event_as_action` /
    `classify_pa_event_as_action` (they only call `.role(addr)`).
    Mirrors the canonical role names used in the production yaml files."""

    _ROLES: dict[str, str] = {
        COMMUNITY_POOL: "community_staking_pool",
        PA_RESERVES_ADDRESS: "pa_reserves",
        PA_FEE_AGGREGATOR_ADDRESS: "pa_fee_aggregator",
        PA_SWAP_AUTOMATOR_ADDRESS: "pa_swap_automator",
    }

    def role(self, address: str) -> str | None:
        return self._ROLES.get(address.lower())


# ---------------------------------------------------------------------------
# CSV writer helper. DuckDB seeds support nested types poorly via CSV, so
# dict / list values are serialized as JSON strings and decoded later (via
# JSON-typed columns or string-typed columns in SQL — we use string columns
# in the seed, which the staging models leave alone).
# ---------------------------------------------------------------------------


def _to_csv_value(v: Any) -> str:
    """Serialize a Python value for CSV. Dicts and lists become JSON
    strings; bools become 'true'/'false'; None becomes '' (empty cell);
    bytes become hex."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, default=str, separators=(",", ":"))
    if isinstance(v, bytes):
        return "0x" + v.hex()
    return str(v)


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    """Write `rows` to `path` with a header row matching `columns`. Rows with
    missing keys produce empty cells. Existing file is overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(columns)
        for r in rows:
            writer.writerow([_to_csv_value(r.get(c)) for c in columns])
    print(f"  wrote {len(rows):>4} rows to {path.relative_to(PROJECT_ROOT)}")


# ---------------------------------------------------------------------------
# Pipeline: process one fixture (logs + trace + receipt + block) and return
# every layer's output as plain dicts ready for CSV emission.
# ---------------------------------------------------------------------------


def _process_stake_fixture(
    fixture: Path,
    run_partition_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """End-to-end real pipeline run for the golden_stake_tx fixture.

    Returns {table_name: [row_dict, ...]} ready to merge with PA outputs
    before serialisation."""
    tx = _load_tx(fixture)
    block = _load_block(fixture)
    receipt = _load_receipt(fixture)
    logs = _load_logs(fixture)
    root_trace = _load_trace(fixture)

    erc20_abi = _erc20_transfer_abi()
    staking_abi = _staking_pool_abi()
    registry = _StubContractRegistry()

    # 1. Decode every log (staked + LINK transfers); collect both sets.
    decoded_events_rows: list[dict[str, Any]] = []
    link_transfer_events = []
    staked_event = None
    for log in logs:
        # Try LINK ERC-20 ABI first (matches all Transfer signature logs).
        decoded = None
        if log.address.lower() == LINK:
            res = decode_log(log, erc20_abi)
            if res.success and res.decoded is not None:
                decoded = res.decoded
                link_transfer_events.append(decoded)
        elif (
            log.address.lower() == COMMUNITY_POOL
            and log.topics
            and log.topics[0].lower() == STAKED_TOPIC0
        ):
            res = decode_log(log, staking_abi)
            if res.success and res.decoded is not None:
                decoded = res.decoded
                staked_event = decoded

        if decoded is not None:
            decoded_events_rows.append(_decoded_event_row(decoded, run_partition_id))

    if staked_event is None:
        raise RuntimeError("golden_stake_tx: no Staked event recovered from real logs")

    # 2. Real trace decode + token-call extraction.
    decoded_calls = decode_trace_calls(root_trace, AbiRegistry({}))
    decoded_calls_rows = [_decoded_call_row(dc, run_partition_id) for dc in decoded_calls]
    receipts_by_tx = {receipt.tx_hash.lower(): receipt}
    trace_token_calls = extract_erc20_transfer_calls(decoded_calls, LINK, receipts_by_tx)

    # 3. Movements: log + trace, then unify.
    log_movements = build_movements_from_transfer_logs(link_transfer_events)
    trace_movements = build_movements_from_trace_calls(trace_token_calls)
    movements = unify_movements(log_movements, trace_movements)
    movements_rows = [_movement_row(m, run_partition_id) for m in movements]

    # 4. Real classification through the staking semantics layer.
    staking_actions: list[EconomicAction] = classify_event_as_action(staked_event, registry)  # type: ignore[arg-type]

    # 5. Reconciliation edges + ledger entries.
    edges_rows: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    actions_rows: list[dict[str, Any]] = []
    for action in staking_actions:
        actions_rows.append(_staking_action_row(action, run_partition_id))
        edges = match_action_to_movements(action, movements)
        edges_rows.extend(_edge_row(e, action, run_partition_id) for e in edges)
        ledger_entries = build_ledger_entries(action, movements)
        ledger_rows.extend(_ledger_row(le, run_partition_id) for le in ledger_entries)

    # 6. Block + canonical-block row (one per fixture).
    blocks_rows = [_canonical_block_row(tx, block, run_partition_id)]

    # 7. LINK transfers seed: only the LINK ERC-20 Transfer logs, as RawLog rows.
    # raw_logs seed: every log we decoded (so the orphan-events test holds).
    # We name the seed `seed_link_transfers` for backwards-compat with the
    # earlier scaffold, but it now includes both LINK Transfer logs AND any
    # other event the decoder recovered (the Staked event on the pool, the
    # AssetTransferredForSwap event on the FeeAggregator, etc.).
    decoded_log_indices = {(de["tx_hash"], de["log_index"]) for de in decoded_events_rows}
    link_transfer_rows: list[dict[str, Any]] = []
    for log in logs:
        # Include any log that produced a decoded event, OR any LINK Transfer.
        is_link_transfer = (
            log.address.lower() == LINK
            and log.topics
            and log.topics[0].lower()
            == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        )
        was_decoded = (log.tx_hash.lower(), log.log_index) in decoded_log_indices
        if not (is_link_transfer or was_decoded):
            continue
        link_transfer_rows.append(_raw_log_row(log, run_partition_id))

    return {
        "decoded_events": decoded_events_rows,
        "decoded_trace_calls": decoded_calls_rows,
        "link_transfers": link_transfer_rows,
        "canonical_blocks": blocks_rows,
        "economic_actions": actions_rows,
        "token_movements": movements_rows,
        "action_movement_edges": edges_rows,
        "ledger_entries": ledger_rows,
    }


def _process_pa_fixture(
    fixture: Path,
    run_partition_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """End-to-end pipeline run for the golden_pa_tx fixture. Same shape as
    the stake one but exercises the PA semantics layer + PA ledger builder."""
    tx = _load_tx(fixture)
    block = _load_block(fixture)
    receipt = _load_receipt(fixture)
    logs = _load_logs(fixture)
    root_trace = _load_trace(fixture)

    erc20_abi = _erc20_transfer_abi()
    fa_abi = _fee_aggregator_abi()
    registry = _StubContractRegistry()

    # 1. Decode logs.
    decoded_events_rows: list[dict[str, Any]] = []
    link_transfer_events = []
    pa_events = []
    for log in logs:
        decoded = None
        if log.address.lower() == LINK:
            res = decode_log(log, erc20_abi)
            if res.success and res.decoded is not None:
                decoded = res.decoded
                link_transfer_events.append(decoded)
        elif (
            log.address.lower() == PA_FEE_AGGREGATOR_ADDRESS
            and log.topics
            and log.topics[0].lower() == ASSET_TRANSFERRED_FOR_SWAP_TOPIC0
        ):
            res = decode_log(log, fa_abi)
            if res.success and res.decoded is not None:
                decoded = res.decoded
                pa_events.append(decoded)

        if decoded is not None:
            decoded_events_rows.append(_decoded_event_row(decoded, run_partition_id))

    # 2. Trace decode for trace token calls.
    decoded_calls = decode_trace_calls(root_trace, AbiRegistry({}))
    decoded_calls_rows = [_decoded_call_row(dc, run_partition_id) for dc in decoded_calls]
    receipts_by_tx = {receipt.tx_hash.lower(): receipt}
    trace_token_calls = extract_erc20_transfer_calls(decoded_calls, LINK, receipts_by_tx)

    # 3. Movements from logs + trace, unified.
    log_movements = build_movements_from_transfer_logs(link_transfer_events)
    trace_movements = build_movements_from_trace_calls(trace_token_calls)
    movements = unify_movements(log_movements, trace_movements)
    movements_rows = [_movement_row(m, run_partition_id) for m in movements]

    # 4. PA action classification: in production the PA contracts emit
    #    Deposited / FeesReceived events that drive `classify_pa_event_as_action`.
    #    The mainnet golden fixture currently only carries the FeeAggregator's
    #    `AssetTransferredForSwap` event — a name not yet wired into the
    #    semantics map (we don't modify the production semantics layer just
    #    for the demo). Instead we observe PA flow at the LINK-Transfer-log
    #    level: every Transfer whose `to` is one of the PA contracts becomes
    #    a real RESERVES_DEPOSIT / FEE_RECEIVED action. All values come from
    #    the decoded log; no fabrication.
    pa_actions: list[PAEconomicAction] = []
    for ev in pa_events:
        pa_actions.extend(classify_pa_event_as_action(ev, registry))  # type: ignore[arg-type]
    pa_actions.extend(_synthesize_pa_actions_from_link_transfers(link_transfer_events))

    # PA actions are NOT surfaced in `int_economic_actions` (that table's
    # `kind` enum is staking-only — `accepted_values` test in
    # `dbt/models/intermediate/schema.yml`). Their balanced ledger entries DO
    # land in `seed_ledger_entries.csv` so the headline `marts.ledger_entries`
    # reflects every real LINK movement.

    # 5. PA reconciliation: PA actions are NOT routed through
    #    `match_action_to_movements` (that one is staking-typed). For the PA
    #    side we emit a single EXACT-or-UNMATCHED edge per action by checking
    #    if there's a movement with matching amount on the same tx.
    edges_rows: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    actions_rows: list[dict[str, Any]] = []
    # PA actions skip `seed_economic_actions` (their `kind` enum doesn't
    # match staking's `accepted_values`). Edges + ledger entries are still
    # emitted so the reconciliation + ledger marts see the real PA flow.
    for action in pa_actions:
        edges_rows.extend(_pa_edge_rows(action, movements, run_partition_id))
        ledger_entries = build_pa_ledger_entries(action)
        ledger_rows.extend(_pa_ledger_row(le, run_partition_id) for le in ledger_entries)

    blocks_rows = [_canonical_block_row(tx, block, run_partition_id)]

    # raw_logs seed: every log we decoded (so the orphan-events test holds).
    # We name the seed `seed_link_transfers` for backwards-compat with the
    # earlier scaffold, but it now includes both LINK Transfer logs AND any
    # other event the decoder recovered (the Staked event on the pool, the
    # AssetTransferredForSwap event on the FeeAggregator, etc.).
    decoded_log_indices = {(de["tx_hash"], de["log_index"]) for de in decoded_events_rows}
    link_transfer_rows: list[dict[str, Any]] = []
    for log in logs:
        # Include any log that produced a decoded event, OR any LINK Transfer.
        is_link_transfer = (
            log.address.lower() == LINK
            and log.topics
            and log.topics[0].lower()
            == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        )
        was_decoded = (log.tx_hash.lower(), log.log_index) in decoded_log_indices
        if not (is_link_transfer or was_decoded):
            continue
        link_transfer_rows.append(_raw_log_row(log, run_partition_id))

    return {
        "decoded_events": decoded_events_rows,
        "decoded_trace_calls": decoded_calls_rows,
        "link_transfers": link_transfer_rows,
        "canonical_blocks": blocks_rows,
        "economic_actions": actions_rows,
        "token_movements": movements_rows,
        "action_movement_edges": edges_rows,
        "ledger_entries": ledger_rows,
    }


# ---------------------------------------------------------------------------
# Row-shaping helpers — one per dbt seed, in column order.
# ---------------------------------------------------------------------------


def _decoded_event_row(de: Any, run_partition_id: str) -> dict[str, Any]:
    return {
        "raw_log_id": de.raw_log_id,
        "decoded_event_id": de.decoded_event_id,
        "chain_id": de.chain_id,
        "block_number": de.block_number,
        "block_hash": "",  # not on DecodedEvent; left blank for joins
        "tx_hash": de.tx_hash.lower(),
        "log_index": de.log_index,
        "contract_address": de.contract_address.lower(),
        "event_name": de.event_name,
        "event_signature": de.event_signature,
        "indexed_params": de.indexed_params,
        "data_params": de.data_params,
        "run_partition_id": run_partition_id,
    }


def _decoded_call_row(dc: Any, run_partition_id: str) -> dict[str, Any]:
    return {
        "raw_trace_call_id": dc.raw_trace_call_id,
        "chain_id": dc.chain_id,
        "block_number": dc.block_number,
        "tx_hash": dc.tx_hash.lower(),
        "trace_address": dc.trace_address,  # list[int] -> JSON string
        "contract_address": (dc.contract_address or "").lower(),
        "method_name": dc.method_name,
        "method_selector": dc.method_selector,
        "params": dc.params,
        "success": dc.success,
        "parent_success": dc.parent_success,
        "run_partition_id": run_partition_id,
    }


def _movement_row(m: TokenMovement, run_partition_id: str) -> dict[str, Any]:
    return {
        "movement_id": m.movement_id,
        "chain_id": m.chain_id,
        "block_number": m.block_number,
        "tx_hash": m.tx_hash.lower(),
        "token_address": m.token_address.lower(),
        "from_addr": m.from_addr.lower(),
        "to_addr": m.to_addr.lower(),
        "amount": m.amount,
        "evidence_ids": m.evidence_ids,
        "source_priority": m.source_priority,
        "is_canonical": m.is_canonical,
        "run_partition_id": run_partition_id,
    }


def _staking_action_row(a: EconomicAction, run_partition_id: str) -> dict[str, Any]:
    return {
        "action_id": a.action_id,
        "kind": a.kind.value,
        "chain_id": a.chain_id,
        "block_number": a.block_number,
        "tx_hash": a.tx_hash.lower(),
        "log_index": a.log_index,
        "contract_address": a.contract_address.lower(),
        "pool_role": a.pool_role,
        "wallet": (a.wallet or "").lower(),
        "amount_link": a.amount_link,
        "source_event_signature": a.source_event_signature,
        "raw_log_id": a.raw_log_id,
        "decoded_event_id": a.decoded_event_id,
        "run_partition_id": run_partition_id,
    }


def _edge_row(
    e: ActionMovementMatch,
    action: EconomicAction,
    run_partition_id: str,
) -> dict[str, Any]:
    return {
        "edge_id": e.edge_id,
        "action_id": e.action_id or "",
        "movement_id": e.movement_id or "",
        "allocated_amount": e.allocated_amount,
        "status": e.status.value,
        "method": e.method.value if e.method else "",
        "reason": e.reason,
        "chain_id": action.chain_id,
        "block_number": action.block_number,
        "tx_hash": action.tx_hash.lower(),
        "run_partition_id": run_partition_id,
    }


def _pa_edge_rows(
    action: PAEconomicAction,
    movements: list[TokenMovement],
    run_partition_id: str,
) -> list[dict[str, Any]]:
    """PA reconciliation: simple amount match against unified movements in
    the same tx. Generates 1 edge per action (EXACT or UNMATCHED). For
    config-only PA actions we emit a single NOT_EXPECTED edge."""
    target = action.output_amount or action.source_amount
    if action.kind == PAActionKind.CONFIG_CHANGED or target == 0:
        edge_id = _hash(f"pa_edge|{action.action_id}|not_expected")
        return [
            {
                "edge_id": edge_id,
                "action_id": action.action_id,
                "movement_id": "",
                "allocated_amount": 0,
                "status": Status.NOT_EXPECTED.value,
                "method": "",
                "reason": f"{action.kind.value} has no expected movement",
                "chain_id": action.chain_id,
                "block_number": action.block_number,
                "tx_hash": action.tx_hash.lower(),
                "run_partition_id": run_partition_id,
            }
        ]

    candidates = [
        m for m in movements if m.tx_hash.lower() == action.tx_hash.lower() and m.amount == target
    ]
    if not candidates:
        edge_id = _hash(f"pa_edge|{action.action_id}|unmatched")
        return [
            {
                "edge_id": edge_id,
                "action_id": action.action_id,
                "movement_id": "",
                "allocated_amount": 0,
                "status": Status.UNMATCHED.value,
                "method": "",
                "reason": "no PA movement with matching amount",
                "chain_id": action.chain_id,
                "block_number": action.block_number,
                "tx_hash": action.tx_hash.lower(),
                "run_partition_id": run_partition_id,
            }
        ]
    m = candidates[0]
    edge_id = _hash(f"pa_edge|{action.action_id}|{m.movement_id}|exact")
    method = "event_log" if m.source_priority == "log" else "trace"
    return [
        {
            "edge_id": edge_id,
            "action_id": action.action_id,
            "movement_id": m.movement_id,
            "allocated_amount": m.amount,
            "status": Status.EXACT.value,
            "method": method,
            "reason": "PA action amount matches token movement",
            "chain_id": action.chain_id,
            "block_number": action.block_number,
            "tx_hash": action.tx_hash.lower(),
            "run_partition_id": run_partition_id,
        }
    ]


def _ledger_row(le: Any, run_partition_id: str) -> dict[str, Any]:
    return {
        "entry_id": le.entry_id,
        "action_id": le.action_id,
        "entry_index": le.entry_index,
        "account": le.account,
        "direction": le.direction.value,
        "amount_link": le.amount_link,
        "chain_id": le.chain_id,
        "block_number": le.block_number,
        "tx_hash": le.tx_hash.lower(),
        "run_partition_id": run_partition_id,
    }


def _pa_ledger_row(le: Any, run_partition_id: str) -> dict[str, Any]:
    return {
        "entry_id": le.entry_id,
        "action_id": le.action_id,
        "entry_index": le.entry_index,
        "account": le.account,
        "direction": le.direction.value if isinstance(le.direction, PADirection) else le.direction,
        "amount_link": le.amount_link,
        "chain_id": le.chain_id,
        "block_number": le.block_number,
        "tx_hash": le.tx_hash.lower(),
        "run_partition_id": run_partition_id,
    }


def _canonical_block_row(
    tx: dict[str, Any],
    block: dict[str, Any],
    run_partition_id: str,
) -> dict[str, Any]:
    return {
        "chain_id": 1,
        "block_number": int(tx["blockNumber"], 16),
        "block_hash": block.get("hash", tx["blockHash"]).lower(),
        "parent_hash": block["parentHash"].lower(),
        "timestamp": int(block["timestamp"], 16),
        "ingested_at": int(block["timestamp"], 16),
        "run_partition_id": run_partition_id,
    }


def _raw_log_row(log: RawLog, run_partition_id: str) -> dict[str, Any]:
    """Filtered LINK transfer raw_log row; dbt staging filters can recover
    the staging shape from this."""
    return {
        "chain_id": log.chain_id,
        "block_number": log.block_number,
        "block_hash": log.block_hash.lower(),
        "tx_hash": log.tx_hash.lower(),
        "tx_index": log.tx_index,
        "log_index": log.log_index,
        "address": log.address.lower(),
        "topics": log.topics,
        "data": log.data,
        "ingested_at": 0,  # placeholder; not used downstream in local target
        "run_partition_id": run_partition_id,
    }


# ---------------------------------------------------------------------------
# Misc small helpers.
# ---------------------------------------------------------------------------


def _hash(s: str) -> str:
    import hashlib

    return hashlib.sha256(s.encode()).hexdigest()


def _synthesize_pa_actions_from_link_transfers(
    link_transfer_events: list[Any],
) -> list[PAEconomicAction]:
    """Build real PAEconomicAction rows from the LINK Transfer events whose
    receiver is a known PA contract. Treats:

      - Transfer(to=Reserves)        → RESERVES_DEPOSIT
      - Transfer(to=FeeAggregator)   → FEE_RECEIVED
      - Transfer(to=SwapAutomator)   → SERVICE_FEE_FORWARDED

    Every field derives from the decoded event — no synthetic values."""
    out: list[PAEconomicAction] = []
    for ev in link_transfer_events:
        to_addr = str(ev.indexed_params.get("to", "")).lower()
        from_addr = str(ev.indexed_params.get("from", "")).lower()
        amount = int(ev.data_params.get("value", 0))
        if amount <= 0:
            continue

        if to_addr == PA_RESERVES_ADDRESS:
            kind = PAActionKind.RESERVES_DEPOSIT
            role = "pa_reserves"
        elif to_addr == PA_FEE_AGGREGATOR_ADDRESS:
            kind = PAActionKind.FEE_RECEIVED
            role = "pa_fee_aggregator"
        elif to_addr == PA_SWAP_AUTOMATOR_ADDRESS:
            kind = PAActionKind.SERVICE_FEE_FORWARDED
            role = "pa_swap_automator"
        else:
            continue

        action_id = _hash(f"pa_action|{ev.decoded_event_id}|{kind.value}")
        out.append(
            PAEconomicAction(
                action_id=action_id,
                kind=kind,
                chain_id=ev.chain_id,
                block_number=ev.block_number,
                tx_hash=ev.tx_hash.lower(),
                log_index=ev.log_index,
                contract_address=to_addr,  # the PA contract receiving the LINK
                contract_role=role,
                source_token=LINK,
                output_token=LINK,
                source_amount=amount,
                output_amount=amount,
                counterparty=from_addr,
                source_event_signature=ev.event_signature,
                raw_log_id=ev.raw_log_id,
                decoded_event_id=ev.decoded_event_id,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Schema definitions for each seed (column order locked here).
# ---------------------------------------------------------------------------

DECODED_EVENTS_COLS = [
    "raw_log_id",
    "decoded_event_id",
    "chain_id",
    "block_number",
    "block_hash",
    "tx_hash",
    "log_index",
    "contract_address",
    "event_name",
    "event_signature",
    "indexed_params",
    "data_params",
    "run_partition_id",
]

DECODED_TRACE_CALLS_COLS = [
    "raw_trace_call_id",
    "chain_id",
    "block_number",
    "tx_hash",
    "trace_address",
    "contract_address",
    "method_name",
    "method_selector",
    "params",
    "success",
    "parent_success",
    "run_partition_id",
]

LINK_TRANSFERS_COLS = [
    "chain_id",
    "block_number",
    "block_hash",
    "tx_hash",
    "tx_index",
    "log_index",
    "address",
    "topics",
    "data",
    "ingested_at",
    "run_partition_id",
]

CANONICAL_BLOCKS_COLS = [
    "chain_id",
    "block_number",
    "block_hash",
    "parent_hash",
    "timestamp",
    "ingested_at",
    "run_partition_id",
]

ECONOMIC_ACTIONS_COLS = [
    "action_id",
    "kind",
    "chain_id",
    "block_number",
    "tx_hash",
    "log_index",
    "contract_address",
    "pool_role",
    "wallet",
    "amount_link",
    "source_event_signature",
    "raw_log_id",
    "decoded_event_id",
    "run_partition_id",
]

TOKEN_MOVEMENTS_COLS = [
    "movement_id",
    "chain_id",
    "block_number",
    "tx_hash",
    "token_address",
    "from_addr",
    "to_addr",
    "amount",
    "evidence_ids",
    "source_priority",
    "is_canonical",
    "run_partition_id",
]

ACTION_MOVEMENT_EDGES_COLS = [
    "edge_id",
    "action_id",
    "movement_id",
    "allocated_amount",
    "status",
    "method",
    "reason",
    "chain_id",
    "block_number",
    "tx_hash",
    "run_partition_id",
]

LEDGER_ENTRIES_COLS = [
    "entry_id",
    "action_id",
    "entry_index",
    "account",
    "direction",
    "amount_link",
    "chain_id",
    "block_number",
    "tx_hash",
    "run_partition_id",
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("seed_to_local: running real decode pipeline on golden fixtures…")
    run_partition_id = "local-demo-2026-05-11"

    stake_outputs = _process_stake_fixture(FIXTURES / "golden_stake_tx", run_partition_id)
    print(f"  golden_stake_tx → {sum(len(v) for v in stake_outputs.values())} total rows")

    pa_outputs = _process_pa_fixture(FIXTURES / "golden_pa_tx", run_partition_id)
    print(f"  golden_pa_tx    → {sum(len(v) for v in pa_outputs.values())} total rows")

    # Merge per-table rows from both fixtures. De-dup on stable id columns.
    def _merge(*lists: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for lst in lists:
            for row in lst:
                k = str(row.get(key, ""))
                if k and k not in seen:
                    seen[k] = row
        return list(seen.values())

    decoded_events = _merge(
        stake_outputs["decoded_events"],
        pa_outputs["decoded_events"],
        key="decoded_event_id",
    )
    decoded_calls = _merge(
        stake_outputs["decoded_trace_calls"],
        pa_outputs["decoded_trace_calls"],
        key="raw_trace_call_id",
    )
    # link_transfers need a COMPOSITE dedup key (tx_hash, log_index) — a single
    # tx_hash isn't unique here because a transaction can emit multiple LINK
    # Transfer logs (e.g. our stake fixture emits 4 LINK transfers in one tx).
    link_seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in stake_outputs["link_transfers"] + pa_outputs["link_transfers"]:
        link_seen[(row["tx_hash"], row["log_index"])] = row
    link_transfers = list(link_seen.values())

    blocks = _merge(
        stake_outputs["canonical_blocks"],
        pa_outputs["canonical_blocks"],
        key="block_number",
    )
    actions = _merge(
        stake_outputs["economic_actions"],
        pa_outputs["economic_actions"],
        key="action_id",
    )
    movements = _merge(
        stake_outputs["token_movements"],
        pa_outputs["token_movements"],
        key="movement_id",
    )
    edges = _merge(
        stake_outputs["action_movement_edges"],
        pa_outputs["action_movement_edges"],
        key="edge_id",
    )
    ledger = _merge(
        stake_outputs["ledger_entries"],
        pa_outputs["ledger_entries"],
        key="entry_id",
    )

    # Sanity: ensure every action_id referenced by an edge that resolves to
    # a staking action also exists in `seed_economic_actions`. PA action ids
    # are intentionally absent from `seed_economic_actions` (different `kind`
    # enum) but their ledger entries do land in `seed_ledger_entries`.
    staking_action_ids = {a["action_id"] for a in actions}
    _pa_account_prefixes = (
        "pa_",
        "upstream:",
        "forwarded_to:",
        "service_contract:",
    )
    pa_ledger_action_ids = {
        r["action_id"]
        for r in ledger
        if any(r["account"].startswith(p) for p in _pa_account_prefixes)
    }
    known_action_ids = staking_action_ids | pa_ledger_action_ids
    for e in edges:
        aid = e["action_id"]
        if aid and aid not in known_action_ids:
            raise RuntimeError(f"edge {e['edge_id']} references unknown action_id {aid}")

    # Write all seeds.
    print("\nseed_to_local: writing CSVs to dbt/seeds/")
    _write_csv(SEED_DIR / "seed_decoded_events.csv", decoded_events, DECODED_EVENTS_COLS)
    _write_csv(
        SEED_DIR / "seed_decoded_trace_calls.csv",
        decoded_calls,
        DECODED_TRACE_CALLS_COLS,
    )
    _write_csv(SEED_DIR / "seed_link_transfers.csv", link_transfers, LINK_TRANSFERS_COLS)
    _write_csv(SEED_DIR / "seed_canonical_blocks.csv", blocks, CANONICAL_BLOCKS_COLS)
    _write_csv(SEED_DIR / "seed_economic_actions.csv", actions, ECONOMIC_ACTIONS_COLS)
    _write_csv(SEED_DIR / "seed_token_movements.csv", movements, TOKEN_MOVEMENTS_COLS)
    _write_csv(
        SEED_DIR / "seed_action_movement_edges.csv",
        edges,
        ACTION_MOVEMENT_EDGES_COLS,
    )
    _write_csv(SEED_DIR / "seed_ledger_entries.csv", ledger, LEDGER_ENTRIES_COLS)

    print(
        "\nseed_to_local: done. Real ledger entries:",
        len(ledger),
        "actions:",
        len(actions),
        "movements:",
        len(movements),
    )

    # Final sanity check: ledger balances per tx (the same invariant dbt's
    # assert_ledger_balanced_per_tx.sql checks).
    by_tx: dict[str, dict[str, int]] = {}
    for r in ledger:
        bucket = by_tx.setdefault(r["tx_hash"], {"debit": 0, "credit": 0})
        bucket[r["direction"]] += int(r["amount_link"])
    for tx, b in by_tx.items():
        if b["debit"] != b["credit"]:
            raise RuntimeError(
                f"ledger imbalance for {tx}: debit={b['debit']} credit={b['credit']}"
            )
    print("seed_to_local: per-tx ledger invariant holds for", len(by_tx), "txs.")


if __name__ == "__main__":
    main()
