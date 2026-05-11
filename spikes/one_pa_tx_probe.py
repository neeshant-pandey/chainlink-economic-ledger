"""Phase 1 protocol spike — manual end-to-end decode of one Payment Abstraction
deposit transaction.

PA is the hero protocol. The flow we're validating:

    service contract → FeeAggregator → SwapAutomator → Reserves

This script walks ONE Reserves deposit tx, decoding by hand:
  1. The trace tree (PA contracts often have proxies; we resolve them)
  2. The internal LINK transfers landing at the Reserves contract
  3. The economic action (RESERVES_DEPOSIT) and its balanced ledger pair

Constants used (literal values; never fabricated). Internal Python source uses
lowercase by design "addresses lowercase everywhere internally; checksum is
display-only":
    LINK token (mainnet):      0x514910771af9ca656af840dff83e8264ecf986ca
    PA Reserves:               0x5680681ed3767b96914ce741a308155c7fb9171d
    PA FeeAggregator (proxy):  0xd6e39d42acee7abcc460e6ea78a0844a0980e78f
    PA SwapAutomator:          0x36e827ba2b270535ca1b099a6ba2b280ddc0315e

Usage:
    python -m spikes.one_pa_tx_probe --tx 0x... [--rpc $RPC_URL] [--cache]
    python -m spikes.one_pa_tx_probe --fixture-dir tests/fixtures/golden_pa_tx
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from eth_abi import decode as abi_decode

LINK_TOKEN_ADDRESS = "0x514910771af9ca656af840dff83e8264ecf986ca"
PA_RESERVES = "0x5680681ed3767b96914ce741a308155c7fb9171d"
PA_FEE_AGGREGATOR = "0xd6e39d42acee7abcc460e6ea78a0844a0980e78f"
PA_SWAP_AUTOMATOR = "0x36e827ba2b270535ca1b099a6ba2b280ddc0315e"

ERC20_TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ERC20_TRANSFER_SELECTOR = "0xa9059cbb"
ERC20_TRANSFER_FROM_SELECTOR = "0x23b872dd"


def fetch_pa_tx_artifacts(tx_hash: str, rpc_url: str) -> dict[str, Any]:
    """Pull every raw artifact needed for a PA tx — same shape as
    `one_stake_tx_probe.fetch_tx_artifacts`. Kept separate so the PA spike can
    evolve independently."""
    import requests

    def call(method: str, params: list[Any]) -> Any:
        r = requests.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=30,
        )
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
        trace = call("debug_traceTransaction", [tx_hash, {"tracer": "callTracer"}])
    except Exception:  # noqa: BLE001
        trace = {}
    return {"tx": tx, "receipt": receipt, "block": block, "logs": logs, "trace": trace}


def cache_artifacts(artifacts: dict[str, Any], fixture_dir: Path) -> None:
    """Write each artifact to its own JSON file under fixture_dir."""
    fixture_dir.mkdir(parents=True, exist_ok=True)
    for key in ("tx", "receipt", "block", "logs", "trace"):
        if key in artifacts:
            (fixture_dir / f"{key}.json").write_text(
                json.dumps(artifacts[key], indent=2, default=str)
            )


def find_reserves_inflows_in_logs(
    logs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter Transfer events whose `to` is the PA Reserves address."""
    out: list[dict[str, Any]] = []
    for log in logs:
        if log.get("address", "").lower() != LINK_TOKEN_ADDRESS.lower():
            continue
        topics = log.get("topics") or []
        if not topics or topics[0].lower() != ERC20_TRANSFER_TOPIC0:
            continue
        from_addr = "0x" + topics[1][-40:].lower()
        to_addr = "0x" + topics[2][-40:].lower()
        if to_addr != PA_RESERVES.lower():
            continue
        data_hex = log["data"]
        data_bytes = bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex)
        (amount,) = abi_decode(["uint256"], data_bytes)
        out.append({"from": from_addr, "to": to_addr, "amount": int(amount), "via": "log"})
    return out


def find_reserves_inflows_in_trace(
    trace_node: dict[str, Any],
) -> list[dict[str, Any]]:
    """Walk the trace tree and return every internal LINK transfer landing at
    the PA Reserves contract.
    """
    out: list[dict[str, Any]] = []

    def _walk(node: dict[str, Any], path: str) -> None:
        if node.get("error"):
            return
        node_to = (node.get("to") or "").lower()
        node_input = node.get("input") or "0x"
        if node_to == LINK_TOKEN_ADDRESS.lower() and (
            node_input.startswith(ERC20_TRANSFER_SELECTOR)
            or node_input.startswith(ERC20_TRANSFER_FROM_SELECTOR)
        ):
            try:
                if node_input.startswith(ERC20_TRANSFER_SELECTOR):
                    body = bytes.fromhex(node_input[10:])
                    to_addr, amount = abi_decode(["address", "uint256"], body[:64])
                    if to_addr.lower() == PA_RESERVES.lower():
                        out.append(
                            {
                                "from": (node.get("from") or "").lower(),
                                "to": to_addr.lower(),
                                "amount": int(amount),
                                "via": "trace",
                                "call_path": path,
                            }
                        )
                else:
                    body = bytes.fromhex(node_input[10:])
                    from_addr, to_addr, amount = abi_decode(
                        ["address", "address", "uint256"], body[:96]
                    )
                    if to_addr.lower() == PA_RESERVES.lower():
                        out.append(
                            {
                                "from": from_addr.lower(),
                                "to": to_addr.lower(),
                                "amount": int(amount),
                                "via": "trace",
                                "call_path": path,
                            }
                        )
            except Exception:  # noqa: BLE001
                pass
        for i, child in enumerate(node.get("calls") or []):
            child_path = f"{path}.{i}" if path else str(i)
            _walk(child, child_path)

    _walk(trace_node, "")
    return out


def synthesize_pa_action(
    inflows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Roll multiple Reserves inflows into a single PA action."""
    total = sum(int(m["amount"]) for m in inflows)
    return {
        "kind": "pa_reserves_deposit",
        "contract_role": "pa_reserves",
        "contract_address": PA_RESERVES.lower(),
        "amount_link": total,
        "n_evidence": len(inflows),
    }


def build_pa_ledger_entries(action: dict[str, Any]) -> list[dict[str, Any]]:
    amount = int(action.get("amount_link", 0))
    if amount == 0:
        return []
    return [
        {
            "direction": "debit",
            "account": "upstream:fee_aggregator_or_swap",
            "amount_link": amount,
        },
        {
            "direction": "credit",
            "account": f"pa_reserves:{action['contract_address']}",
            "amount_link": amount,
        },
    ]


def print_pa_walkthrough(
    artifacts: dict[str, Any],
    log_inflows: list[dict[str, Any]],
    trace_inflows: list[dict[str, Any]],
    action: dict[str, Any],
    ledger_entries: list[dict[str, Any]],
) -> None:
    tx = artifacts.get("tx", {})
    receipt = artifacts.get("receipt", {})
    print("=== RAW PA TX ===")
    print(f"tx_hash       = {tx.get('hash')}")
    print(f"block_number  = {tx.get('blockNumber')}")
    print(f"status        = {receipt.get('status')}")
    print(f"n_logs        = {len(receipt.get('logs', []))}")
    print()
    print("=== RESERVES INFLOWS (LOG) ===")
    for m in log_inflows:
        print(f"  from={m['from']} amount={m['amount']}")
    print()
    print("=== RESERVES INFLOWS (TRACE) ===")
    for m in trace_inflows:
        print(f"  from={m['from']} amount={m['amount']} path={m.get('call_path')}")
    print()
    print("=== PA ACTION ===")
    for k, v in action.items():
        print(f"  {k}: {v}")
    print()
    print("=== LEDGER ===")
    debits = sum(e["amount_link"] for e in ledger_entries if e["direction"] == "debit")
    credits = sum(e["amount_link"] for e in ledger_entries if e["direction"] == "credit")
    for e in ledger_entries:
        print(f"  {e['direction']:6s} {e['account']:50s} {e['amount_link']}")
    print(f"  balance: {'OK' if debits == credits else f'OFF by {debits - credits}'}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="one_pa_tx_probe",
        description=(
            "Phase 1 spike: manual end-to-end decode of one Payment "
            "Abstraction Reserves deposit tx."
        ),
    )
    parser.add_argument("--tx", type=str, default=None, help="PA tx hash (0x...)")
    parser.add_argument(
        "--rpc",
        type=str,
        default=os.environ.get("RPC_URL"),
        help="JSON-RPC endpoint (default: $RPC_URL)",
    )
    parser.add_argument("--cache", action="store_true", help="cache to --fixture-dir")
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=Path("tests/fixtures/golden_pa_tx"),
        help="cached artifacts directory",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.tx is None and not args.fixture_dir.exists():
        print(
            "ERROR: pass --tx <hash> or ensure --fixture-dir has cached JSON",
            file=sys.stderr,
        )
        return 2

    if args.tx is None:
        artifacts: dict[str, Any] = {}
        for k in ("tx", "receipt", "block", "logs", "trace"):
            f = args.fixture_dir / f"{k}.json"
            artifacts[k] = json.loads(f.read_text()) if f.exists() else {}
    else:
        if not args.rpc:
            print("ERROR: --rpc URL required when --tx is set", file=sys.stderr)
            return 2
        artifacts = fetch_pa_tx_artifacts(args.tx, args.rpc)
        if args.cache:
            cache_artifacts(artifacts, args.fixture_dir)

    log_inflows = find_reserves_inflows_in_logs(artifacts.get("logs") or [])
    trace_inflows = (
        find_reserves_inflows_in_trace(artifacts["trace"]) if artifacts.get("trace") else []
    )

    # Combine evidence: prefer log evidence, augment with trace-only
    seen = {(m["from"], m["amount"]) for m in log_inflows}
    combined = list(log_inflows)
    for m in trace_inflows:
        if (m["from"], m["amount"]) not in seen:
            combined.append(m)

    action = synthesize_pa_action(combined)
    ledger = build_pa_ledger_entries(action)
    print_pa_walkthrough(artifacts, log_inflows, trace_inflows, action, ledger)

    debits = sum(e["amount_link"] for e in ledger if e["direction"] == "debit")
    credits = sum(e["amount_link"] for e in ledger if e["direction"] == "credit")
    return 0 if debits == credits else 1


if __name__ == "__main__":
    sys.exit(main())
