"""Throwaway validation script: hand-decode one Stake transaction end-to-end.

Used during protocol bring-up to remove ABI guesses before writing the
production scaffold. Decodes by hand with `eth_abi` so every step is observable.

Usage:
    python -m spikes.one_stake_tx_probe --tx 0x... [--rpc $RPC_URL] [--cache]
    python -m spikes.one_stake_tx_probe --fixture-dir tests/fixtures/golden_stake_tx
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from eth_abi import decode as abi_decode

# Mainnet LINK token — lowercase form is internal (project convention: addresses lowercase
# everywhere internally; checksum is display-only).
LINK_TOKEN_ADDRESS = "0x514910771af9ca656af840dff83e8264ecf986ca"
ERC20_TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ERC20_TRANSFER_SELECTOR = "0xa9059cbb"
ERC20_TRANSFER_FROM_SELECTOR = "0x23b872dd"

# Verified Staked event signature: `Staked(address,uint256,uint256,uint256)` —
# emitted by the Chainlink Staking v0.2 Community Pool. Computed via keccak256
# and verified against the real log at block 18,671,459.
STAKED_TOPIC0 = "0xb4caaf29adda3eefee3ad552a8e85058589bf834c7466cae4ee58787f70589ed"
COMMUNITY_STAKING_POOL_ADDRESS = "0xbc10f2e862ed4502144c7d632a3459f49dfcdb5e"


def fetch_tx_artifacts(tx_hash: str, rpc_url: str) -> dict[str, Any]:
    """Pull every raw artifact needed to reconstruct one tx via JSON-RPC.

    Uses `requests.post` directly so the wire shape is observable.

    Returns dict with keys: tx, receipt, block, logs, trace.
    """
    import requests

    def call(method: str, params: list[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        r = requests.post(rpc_url, json=payload, timeout=30)
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RuntimeError(f"RPC error: {body['error']}")
        return body["result"]

    tx = call("eth_getTransactionByHash", [tx_hash])
    receipt = call("eth_getTransactionReceipt", [tx_hash])
    block = call("eth_getBlockByNumber", [tx["blockNumber"], False])
    logs = receipt["logs"]
    try:
        trace = call(
            "debug_traceTransaction",
            [tx_hash, {"tracer": "callTracer"}],
        )
    except Exception:  # noqa: BLE001
        trace = {}
    return {"tx": tx, "receipt": receipt, "block": block, "logs": logs, "trace": trace}


def save_artifacts_as_fixtures(artifacts: dict[str, Any], fixture_dir: Path) -> None:
    """Write each artifact to its own JSON file under fixture_dir."""
    fixture_dir.mkdir(parents=True, exist_ok=True)
    for key in ("tx", "receipt", "block", "logs", "trace"):
        if key in artifacts:
            (fixture_dir / f"{key}.json").write_text(
                json.dumps(artifacts[key], indent=2, default=str)
            )


def is_link_transfer_log(log: dict[str, Any], link_token_address: str) -> bool:
    """True iff log.address == LINK token AND topics[0] == ERC-20 Transfer sig."""
    if log.get("address", "").lower() != link_token_address.lower():
        return False
    topics = log.get("topics") or []
    if not topics:
        return False
    return topics[0].lower() == ERC20_TRANSFER_TOPIC0


def decode_link_transfer(log: dict[str, Any]) -> dict[str, Any]:
    """Decode an ERC-20 Transfer log by hand.

    Returns: {"from": str, "to": str, "amount": int}
    """
    topics = log["topics"]
    from_addr = "0x" + topics[1][-40:].lower()
    to_addr = "0x" + topics[2][-40:].lower()
    data_hex = log["data"]
    data_bytes = bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex)
    (amount,) = abi_decode(["uint256"], data_bytes)
    return {"from": from_addr, "to": to_addr, "amount": int(amount)}


def decode_staked_event(log: dict[str, Any], abi_event: dict[str, Any]) -> dict[str, Any]:
    """Decode a Staking v0.2 `Staked` event by hand using its ABI fragment.

    The output shape mirrors what `decoder.event_decoder.decode_log` produces.
    """
    inputs = abi_event.get("inputs", [])
    indexed = [i for i in inputs if i.get("indexed")]
    non_indexed = [i for i in inputs if not i.get("indexed")]

    out: dict[str, Any] = {}
    topics = log["topics"]
    for i, inp in enumerate(indexed):
        topic = topics[1 + i]
        if inp["type"] == "address":
            out[inp["name"]] = "0x" + topic[-40:].lower()
        else:
            out[inp["name"]] = abi_decode([inp["type"]], bytes.fromhex(topic[2:]))[0]

    if non_indexed:
        data_hex = log["data"]
        data_bytes = bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex)
        types = [inp["type"] for inp in non_indexed]
        decoded = abi_decode(types, data_bytes)
        for inp, val in zip(non_indexed, decoded, strict=True):
            out[inp["name"]] = val
    return out


def walk_trace_for_link_transfers(
    trace_node: dict[str, Any],
    link_token_address: str,
) -> list[dict[str, Any]]:
    """Recursively walk a callTracer output and collect internal LINK transfer
    calls (transfer / transferFrom) into the LINK token contract.
    """
    out: list[dict[str, Any]] = []

    def _walk(node: dict[str, Any], call_path: str) -> None:
        if node.get("error"):
            return
        node_to = (node.get("to") or "").lower()
        node_input = node.get("input") or "0x"
        if node_to == link_token_address.lower() and (
            node_input.startswith(ERC20_TRANSFER_SELECTOR)
            or node_input.startswith(ERC20_TRANSFER_FROM_SELECTOR)
        ):
            try:
                if node_input.startswith(ERC20_TRANSFER_SELECTOR):
                    body = bytes.fromhex(node_input[10:])
                    to_addr, amount = abi_decode(["address", "uint256"], body[:64])
                    out.append(
                        {
                            "from": (node.get("from") or "").lower(),
                            "to": to_addr.lower(),
                            "amount": int(amount),
                            "call_path": call_path,
                        }
                    )
                else:
                    body = bytes.fromhex(node_input[10:])
                    from_addr, to_addr, amount = abi_decode(
                        ["address", "address", "uint256"], body[:96]
                    )
                    out.append(
                        {
                            "from": from_addr.lower(),
                            "to": to_addr.lower(),
                            "amount": int(amount),
                            "call_path": call_path,
                        }
                    )
            except Exception:  # noqa: BLE001
                pass

        for i, child in enumerate(node.get("calls") or []):
            child_path = f"{call_path}.{i}" if call_path else str(i)
            _walk(child, child_path)

    _walk(trace_node, "")
    return out


def synthesize_economic_action(decoded_staked: dict[str, Any]) -> dict[str, Any]:
    """Map the decoded Staked event into an EconomicAction-shaped dict."""
    return {
        "kind": "stake",
        "wallet": decoded_staked.get("staker"),
        "amount_link": int(decoded_staked.get("newPrincipal") or decoded_staked.get("amount", 0)),
        "pool_role": "community_pool",
    }


def reconcile_action_to_movements(
    action: dict[str, Any],
    log_transfers: list[dict[str, Any]],
    trace_transfers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Naive 1-tx reconciliation for the spike."""
    target = int(action.get("amount_link", 0))
    matched_log = [m for m in log_transfers if int(m["amount"]) == target]
    matched_trace = [m for m in trace_transfers if int(m["amount"]) == target]
    if matched_log:
        return {
            "status": "exact",
            "matched_movements": matched_log,
            "matched_method": "event_log",
        }
    if matched_trace:
        return {
            "status": "exact",
            "matched_movements": matched_trace,
            "matched_method": "trace",
        }
    return {
        "status": "unmatched",
        "matched_movements": [],
        "matched_method": None,
    }


def build_ledger_entries(
    action: dict[str, Any],
    reconciliation: dict[str, Any],
) -> list[dict[str, Any]]:
    """Produce balanced double-entry rows."""
    amount = int(action.get("amount_link", 0))
    wallet = action.get("wallet", "unknown")
    return [
        {
            "direction": "debit",
            "account": f"wallet:{wallet}",
            "amount_link": amount,
        },
        {
            "direction": "credit",
            "account": f"pool:{action.get('pool_role', 'community_pool')}",
            "amount_link": amount,
        },
    ]


def print_walkthrough(
    artifacts: dict[str, Any],
    decoded: dict[str, Any],
    action: dict[str, Any],
    log_movements: list[dict[str, Any]],
    trace_movements: list[dict[str, Any]],
    reconciliation: dict[str, Any],
    ledger_entries: list[dict[str, Any]],
) -> None:
    tx = artifacts.get("tx", {})
    receipt = artifacts.get("receipt", {})
    print("=== RAW ===")
    print(f"tx_hash       = {tx.get('hash')}")
    print(f"block_number  = {tx.get('blockNumber')}")
    print(f"status        = {receipt.get('status')}")
    print(f"gas_used      = {receipt.get('gasUsed')}")
    print(f"n_logs        = {len(receipt.get('logs', []))}")
    print()
    print("=== DECODED EVENT ===")
    for k, v in decoded.items():
        print(f"  {k}: {v}")
    print()
    print("=== MOVEMENTS ===")
    for m in log_movements:
        print(f"  [log]   from={m['from']} to={m['to']} amount={m['amount']}")
    for m in trace_movements:
        print(f"  [trace] from={m['from']} to={m['to']} amount={m['amount']} path={m['call_path']}")
    print()
    print("=== ECONOMIC ACTION ===")
    for k, v in action.items():
        print(f"  {k}: {v}")
    print()
    print("=== RECONCILIATION ===")
    print(f"  status={reconciliation['status']} method={reconciliation['matched_method']}")
    print()
    print("=== LEDGER ===")
    debits = sum(e["amount_link"] for e in ledger_entries if e["direction"] == "debit")
    credits = sum(e["amount_link"] for e in ledger_entries if e["direction"] == "credit")
    for e in ledger_entries:
        print(f"  {e['direction']:6s} {e['account']:50s} {e['amount_link']}")
    balanced = "OK" if debits == credits else f"OFF by {debits - credits}"
    print(f"  balance: {balanced}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="one_stake_tx_probe",
        description="Phase 1 spike: manual end-to-end decode of one Stake tx.",
    )
    parser.add_argument(
        "--tx",
        type=str,
        default=None,
        help="staking transaction hash (0x...); if omitted, --fixture-dir is required",
    )
    parser.add_argument(
        "--rpc",
        type=str,
        default=os.environ.get("RPC_URL"),
        help="JSON-RPC endpoint (default: $RPC_URL)",
    )
    parser.add_argument(
        "--cache",
        action="store_true",
        help="cache fetched artifacts to --fixture-dir for offline replay",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=Path("tests/fixtures/golden_stake_tx"),
        help="path to load/store cached RPC artifacts",
    )
    parser.add_argument(
        "--abi",
        type=Path,
        default=None,
        help="optional path to staking pool ABI JSON (for richer decoding)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """argparse → fetch → cache (optional) → decode → reconcile → print."""
    args = _parse_args(argv)

    if args.tx is None and not args.fixture_dir.exists():
        print(
            "ERROR: pass --tx <hash> or ensure --fixture-dir contains cached "
            "tx.json/receipt.json/logs.json/trace.json",
            file=sys.stderr,
        )
        return 2

    # Load artifacts: prefer fixture cache if --tx not given
    if args.tx is None:
        artifacts = {}
        for k in ("tx", "receipt", "block", "logs", "trace"):
            f = args.fixture_dir / f"{k}.json"
            artifacts[k] = json.loads(f.read_text()) if f.exists() else {}
    else:
        if not args.rpc:
            print("ERROR: --rpc URL required when --tx is set", file=sys.stderr)
            return 2
        artifacts = fetch_tx_artifacts(args.tx, args.rpc)
        if args.cache:
            save_artifacts_as_fixtures(artifacts, args.fixture_dir)

    # Find the REAL Staked log: must be emitted by the Community Staking Pool
    # AND topic0 must match the verified `Staked(address,uint256,uint256,uint256)`
    # signature. We do NOT iterate-and-try every non-LINK log — that picks up
    # router/proxy events that happen to decode without errors and produces a
    # wrong staker (e.g. the wallet that submitted the tx, not the wallet the
    # router staked on behalf of).
    logs = artifacts.get("logs") or []
    log_movements: list[dict[str, Any]] = []
    decoded_action_event: dict[str, Any] = {}

    # Default to the verified 4-arg `Staked(address,uint256,uint256,uint256)` ABI.
    # An earlier 2-arg guess produced a DIFFERENT topic0 that does not match
    # the on-chain log; the 4-arg form is canonical for Staking v0.2.
    abi_event_def = {
        "type": "event",
        "name": "Staked",
        "inputs": [
            {"name": "staker", "type": "address", "indexed": True},
            {"name": "newPrincipal", "type": "uint256", "indexed": False},
            {"name": "newAllowance", "type": "uint256", "indexed": False},
            {"name": "maxPrincipal", "type": "uint256", "indexed": False},
        ],
    }
    if args.abi and args.abi.exists():
        with args.abi.open() as f:
            abi_json = json.load(f)
        for entry in abi_json:
            if entry.get("type") == "event" and entry.get("name") == "Staked":
                abi_event_def = entry
                break

    for log in logs:
        if is_link_transfer_log(log, LINK_TOKEN_ADDRESS):
            log_movements.append(decode_link_transfer(log))
        elif (
            not decoded_action_event
            and (log.get("address") or "").lower() == COMMUNITY_STAKING_POOL_ADDRESS
            and (log.get("topics") or [None])[0] == STAKED_TOPIC0
        ):
            # Fail loudly on decode errors — silent fallback hid a bug where the
            # spike accepted the first non-LINK log and reported the wrong staker.
            decoded_action_event = decode_staked_event(log, abi_event_def)

    # Trace movements
    trace_movements: list[dict[str, Any]] = []
    if artifacts.get("trace"):
        try:
            trace_movements = walk_trace_for_link_transfers(artifacts["trace"], LINK_TOKEN_ADDRESS)
        except Exception:  # noqa: BLE001
            trace_movements = []

    action = synthesize_economic_action(decoded_action_event or {})
    reconciliation = reconcile_action_to_movements(action, log_movements, trace_movements)
    ledger = build_ledger_entries(action, reconciliation)

    print_walkthrough(
        artifacts=artifacts,
        decoded=decoded_action_event,
        action=action,
        log_movements=log_movements,
        trace_movements=trace_movements,
        reconciliation=reconciliation,
        ledger_entries=ledger,
    )

    debits = sum(e["amount_link"] for e in ledger if e["direction"] == "debit")
    credits = sum(e["amount_link"] for e in ledger if e["direction"] == "credit")
    return 0 if debits == credits else 1


if __name__ == "__main__":
    sys.exit(main())
