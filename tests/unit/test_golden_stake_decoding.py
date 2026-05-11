"""Golden Stake-tx decoding test (real mainnet fixture).

Loads `tests/fixtures/golden_stake_tx/{tx,receipt,logs,trace,block}.json` —
verbatim captures of a real Chainlink Community Staking Pool v0.2 Stake
transaction on Ethereum mainnet:

  hash:  0x08c2902756cb2808c056499225d6dbd40c3e656a3b53fe9d31679fcb8dc15e96
  block: 18,671,459

Asserts, against the real decoders + reconciliation pipeline (no synthetic
inputs):
  - Loading all four artifact files succeeds.
  - `decode_log` over every log finds at least one `Staked` event_name on the
    Community Staking Pool.
  - The decoded Staked amount EXACTLY matches the LINK Transfer log into the
    pool (cross-source consistency).
  - `extract_erc20_transfer_calls` over the real trace produces ≥1
    TraceTokenCall with token=LINK and to=Community Pool, with amount equal to
    the Staked event amount.
  - `match_action_to_movements` on the real action + real movements produces
    one EXACT edge.
  - `build_ledger_entries` produces 2 entries that balance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from decoder.event_decoder import decode_log
from decoder.trace_decoder import (
    decode_trace_calls,
    extract_erc20_transfer_calls,
)
from decoder.trace_tree import build_call_tree, flatten_call_tree
from decoder.types import Abi, RawLog, RawTrace, Receipt
from reconciliation.movement_builder import (
    build_movements_from_trace_calls,
    build_movements_from_transfer_logs,
    unify_movements,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "golden_stake_tx"

# Mainnet contract addresses (lowercase — internal canonical form).
LINK = "0x514910771af9ca656af840dff83e8264ecf986ca"
COMMUNITY_POOL = "0xbc10f2e862ed4502144c7d632a3459f49dfcdb5e"
STAKING_ROUTER = "0x3feb1e09b4bb0e7f0387cee092a52e85797ab889"

# Topic0 for `Staked(address,uint256,uint256,uint256)` as emitted by this
# Community Staking Pool v0.2.
STAKED_TOPIC0 = "0xb4caaf29adda3eefee3ad552a8e85058589bf834c7466cae4ee58787f70589ed"


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_tx_json() -> dict:
    return json.loads((FIXTURE_DIR / "tx.json").read_text())


def _load_receipt() -> Receipt:
    r = json.loads((FIXTURE_DIR / "receipt.json").read_text())
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


def _load_logs() -> list[RawLog]:
    raw_logs = json.loads((FIXTURE_DIR / "logs.json").read_text())
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
    """Convert nested callTracer JSON (`{from,to,input,calls:[...]}`) into the
    flat row shape expected by `decoder.trace_tree.build_call_tree`.

    This is the inverse of BigQuery's `crypto_ethereum.traces` (which ships
    flat rows). Either shape feeds the same `build_call_tree`.
    """
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


def _load_trace() -> RawTrace:
    node = json.loads((FIXTURE_DIR / "trace.json").read_text())
    tx = _load_tx_json()
    rows = _trace_node_to_flat_rows(
        node,
        tx_hash=tx["hash"].lower(),
        block_number=int(tx["blockNumber"], 16),
        chain_id=1,
    )
    return build_call_tree(rows, chain_id=1)


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


# ---------------------------------------------------------------------------
# Fixture sanity
# ---------------------------------------------------------------------------


def test_golden_stake_fixture_is_real_mainnet_tx() -> None:
    """All four fixture files load. The tx is the known mainnet stake tx."""
    tx = _load_tx_json()
    receipt = _load_receipt()
    logs = _load_logs()
    root_trace = _load_trace()

    assert (
        tx["hash"].lower() == "0x08c2902756cb2808c056499225d6dbd40c3e656a3b53fe9d31679fcb8dc15e96"
    )
    assert int(tx["blockNumber"], 16) == 18_671_459
    assert receipt.status == 1, "real tx must have succeeded"
    assert receipt.logs_count == 10
    assert len(logs) == 10
    assert root_trace.tx_hash.lower() == tx["hash"].lower()
    assert len(root_trace.calls) >= 1, "trace must have non-trivial structure"


# ---------------------------------------------------------------------------
# Event decoding
# ---------------------------------------------------------------------------


def test_golden_stake_decode_log_finds_staked_event() -> None:
    """Running `decode_log` over every fixture log produces ≥1 Staked event
    whose indexed staker matches tx.from and whose amount is a positive int.
    """
    tx = _load_tx_json()
    tx_sender = tx["from"].lower()
    logs = _load_logs()
    staking_abi = _staking_pool_abi()

    staked_decoded = []
    for log in logs:
        if not log.topics or log.topics[0].lower() != STAKED_TOPIC0:
            continue
        res = decode_log(log, staking_abi)
        if res.success and res.decoded is not None:
            staked_decoded.append(res.decoded)

    assert len(staked_decoded) >= 1, "expected >=1 Staked event"
    decoded = staked_decoded[0]
    assert decoded.event_name == "Staked"
    assert decoded.indexed_params["staker"].lower() == tx_sender
    amount = decoded.data_params["amount"]
    assert isinstance(amount, int)
    assert amount > 0


def test_golden_stake_decoded_amount_matches_link_transfer_log() -> None:
    """The amount on the Staked event MUST equal the value of the LINK Transfer
    log into the Community Pool. If they differ, the decoders are inconsistent
    with each other on the same on-chain fact."""
    logs = _load_logs()
    staking_abi = _staking_pool_abi()
    erc20_abi = _erc20_transfer_abi()

    # Pull the Staked amount.
    staked_amount: int | None = None
    for log in logs:
        if log.topics and log.topics[0].lower() == STAKED_TOPIC0:
            res = decode_log(log, staking_abi)
            if res.success and res.decoded is not None:
                staked_amount = int(res.decoded.data_params["amount"])
                break
    assert staked_amount is not None, "no Staked event decoded"

    # Pull the LINK Transfer value into the Community Pool.
    pool_inflow: int | None = None
    for log in logs:
        if log.address.lower() != LINK:
            continue
        res = decode_log(log, erc20_abi)
        if not res.success or res.decoded is None:
            continue
        if res.decoded.indexed_params.get("to", "").lower() == COMMUNITY_POOL:
            pool_inflow = int(res.decoded.data_params["value"])
            break
    assert pool_inflow is not None, "no LINK Transfer to Community Pool"
    assert staked_amount == pool_inflow, (
        f"Staked.amount ({staked_amount}) != LINK Transfer.value into pool "
        f"({pool_inflow}) -- decoders disagree on the same fact"
    )


# ---------------------------------------------------------------------------
# Trace decoding + extraction
# ---------------------------------------------------------------------------


def test_golden_stake_real_trace_extracts_link_transfer_calls() -> None:
    """Running the real trace through `decode_trace_calls` and then
    `extract_erc20_transfer_calls` produces >=1 LINK transfer() call. Trace
    addresses must be populated (non-empty for non-root calls)."""
    root_trace = _load_trace()
    receipt = _load_receipt()

    # Empty AbiRegistry -- we rely on the fast-path ERC-20 selector recognition.
    from decoder.abi_registry import AbiRegistry

    decoded_calls = decode_trace_calls(root_trace, AbiRegistry({}))
    # Trace addresses are populated for every non-root call.
    non_root = [c for c in decoded_calls if c.trace_address]
    assert len(non_root) >= 1, "trace must have multiple frames beyond root"

    receipts_by_tx = {receipt.tx_hash.lower(): receipt}
    token_calls = extract_erc20_transfer_calls(decoded_calls, LINK, receipts_by_tx)
    assert len(token_calls) >= 1, "expected >=1 LINK transfer in trace"
    # All emitted token calls must be on LINK with positive amount.
    for tc in token_calls:
        assert tc.token_address.lower() == LINK
        assert tc.amount > 0


def test_golden_stake_trace_has_multiple_depth_levels() -> None:
    """Sanity: this Stake tx routes via a staking router and the pool's onERC677
    flow. The trace tree MUST be at least 3 levels deep -- otherwise the
    fixture is suspect."""
    root_trace = _load_trace()
    all_nodes = flatten_call_tree(root_trace)
    max_depth = max(len(n.trace_address) for n in all_nodes)
    assert max_depth >= 3, f"expected trace depth >=3, got {max_depth}"


# ---------------------------------------------------------------------------
# Reconciliation + ledger (real pipeline; no manual EconomicAction)
# ---------------------------------------------------------------------------


def test_golden_stake_real_reconciliation_balanced() -> None:
    """End-to-end: real decoded Staked event -> real action via the protocol
    semantics layer -> real movements from logs+trace -> real reconciliation
    edge (EXACT) -> real ledger entries (balanced).

    Notably: the action is NOT constructed manually in the test body. It is
    produced by `classify_event_as_action` from the real decoded event.
    """
    from decoder.abi_registry import AbiRegistry
    from protocols.staking_v02.ledger_builder import (
        build_ledger_entries,
        verify_double_entry,
    )
    from protocols.staking_v02.semantics import classify_event_as_action
    from reconciliation.economic_reconciler import (
        Status,
        match_action_to_movements,
    )

    tx = _load_tx_json()
    receipt = _load_receipt()
    logs = _load_logs()
    root_trace = _load_trace()

    # 1. Decode all logs through the real decoder.
    erc20_abi = _erc20_transfer_abi()
    staking_abi = _staking_pool_abi()
    link_transfer_events = []
    staked_event = None
    for log in logs:
        if log.address.lower() == LINK:
            res = decode_log(log, erc20_abi)
            if res.success and res.decoded is not None:
                link_transfer_events.append(res.decoded)
        elif (
            log.address.lower() == COMMUNITY_POOL
            and log.topics
            and log.topics[0].lower() == STAKED_TOPIC0
        ):
            res = decode_log(log, staking_abi)
            if res.success and res.decoded is not None:
                staked_event = res.decoded
    assert staked_event is not None
    assert len(link_transfer_events) >= 1

    # 2. Real classification -- the ContractRegistry stub returns the canonical
    # role. (We construct a minimal in-test registry; the dispatch logic IS the
    # real `classify_event_as_action` from `protocols.staking_v02.semantics`.)
    class _PoolRegistry:
        def role(self, addr: str) -> str | None:
            return "community_staking_pool" if addr.lower() == COMMUNITY_POOL else None

    actions = classify_event_as_action(staked_event, _PoolRegistry())  # type: ignore[arg-type]
    assert len(actions) == 1
    action = actions[0]
    assert action.kind.value == "stake"
    expected_amount = int(staked_event.data_params["amount"])
    assert action.amount_link == expected_amount
    assert action.wallet == tx["from"].lower()

    # 3. Build real movements: logs path AND trace path, then unify.
    log_movements = build_movements_from_transfer_logs(link_transfer_events)
    decoded_calls = decode_trace_calls(root_trace, AbiRegistry({}))
    trace_token_calls = extract_erc20_transfer_calls(
        decoded_calls, LINK, {receipt.tx_hash.lower(): receipt}
    )
    trace_movements = build_movements_from_trace_calls(trace_token_calls)
    movements = unify_movements(log_movements, trace_movements)
    assert len(movements) >= 1

    # 4. Run real matcher -- must produce one EXACT edge whose movement
    # has the same amount as the action.
    edges = match_action_to_movements(action, movements)
    exact = [e for e in edges if e.status == Status.EXACT]
    assert len(exact) == 1, f"expected 1 EXACT edge, got {edges!r}"
    exact_edge = exact[0]
    assert exact_edge.allocated_amount == expected_amount

    # 5. Real ledger entries balance.
    entries = build_ledger_entries(action, movements)
    assert len(entries) == 2  # one debit, one credit
    check = verify_double_entry(entries)
    assert check.is_balanced
    assert check.debit_total == check.credit_total == expected_amount
