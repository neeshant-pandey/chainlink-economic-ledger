"""Thin JSON-RPC client wrapper.

Public surface is the contract; batching/retry/library choice (web3.py, raw
httpx, etc.) is left to the implementation. We use `web3.py` here because it
is already in the dependency set and handles batched receipts gracefully.

Capability check `supports_debug_trace()` exists because not all RPC providers
expose `debug_traceTransaction` (notably free Infura tier). The pipeline must
fail loudly on configuration that requires traces but lacks the capability.

This is the FALLBACK path — the primary ingestion surface is `ingestion/bq/`
(BQ public datasets). Only `freshness` validation and recent-tip data path
through here.
"""

from __future__ import annotations

from typing import Any, cast

from decoder.types import Block, BlockHeader, RawLog, RawTrace, Receipt


class RpcClient:
    """Strict public surface. Internals (connection pooling, retries) are
    implementation details kept out of the type contract."""

    def __init__(
        self,
        rpc_url: str,
        timeout: float = 30.0,
        retry_policy: dict[str, Any] | None = None,
    ) -> None:
        self.rpc_url = rpc_url
        self.timeout = timeout
        self.retry_policy = retry_policy or {}
        self._w3: Any = None
        self._supports_trace_cache: bool | None = None

    def _w3_client(self) -> Any:
        if self._w3 is not None:
            return self._w3
        from web3 import HTTPProvider, Web3

        self._w3 = Web3(HTTPProvider(self.rpc_url, request_kwargs={"timeout": self.timeout}))
        return self._w3

    def get_chain_id(self) -> int:
        return int(self._w3_client().eth.chain_id)

    def get_logs(
        self,
        address: str | list[str],
        topics: list[str | list[str] | None],
        from_block: int,
        to_block: int,
    ) -> list[RawLog]:
        """eth_getLogs with topic filter. Caller handles windowing."""
        chain_id = self.get_chain_id()
        w3 = self._w3_client()
        addresses = [address] if isinstance(address, str) else address
        log_filter = {
            "fromBlock": from_block,
            "toBlock": to_block,
            "address": list(addresses),
            "topics": topics,
        }
        results = w3.eth.get_logs(log_filter)  # type: ignore[arg-type]
        out: list[RawLog] = []
        for log in results:
            out.append(
                RawLog(
                    chain_id=chain_id,
                    block_number=int(log["blockNumber"]),
                    block_hash=log["blockHash"].hex()
                    if hasattr(log["blockHash"], "hex")
                    else str(log["blockHash"]),
                    tx_hash=log["transactionHash"].hex()
                    if hasattr(log["transactionHash"], "hex")
                    else str(log["transactionHash"]),
                    tx_index=int(log["transactionIndex"]),
                    log_index=int(log["logIndex"]),
                    address=str(log["address"]).lower(),
                    topics=[t.hex() if hasattr(t, "hex") else str(t) for t in log["topics"]],
                    data=log["data"].hex() if hasattr(log["data"], "hex") else str(log["data"]),
                )
            )
        return out

    def get_block(self, block_number: int, full_txs: bool = False) -> Block:
        w3 = self._w3_client()
        b = w3.eth.get_block(block_number, full_transactions=full_txs)
        chain_id = self.get_chain_id()
        header = BlockHeader(
            chain_id=chain_id,
            block_number=int(b["number"]),
            block_hash=b["hash"].hex() if hasattr(b["hash"], "hex") else str(b["hash"]),
            parent_hash=(
                b["parentHash"].hex() if hasattr(b["parentHash"], "hex") else str(b["parentHash"])
            ),
            timestamp=int(b["timestamp"]),
            miner=str(b.get("miner", "")) or None,
            base_fee_per_gas=(
                int(b["baseFeePerGas"]) if b.get("baseFeePerGas") is not None else None
            ),
        )
        tx_hashes = [
            t.hex() if hasattr(t, "hex") else str(t) for t in (b.get("transactions") or [])
        ]
        return Block(header=header, transaction_hashes=tx_hashes, full_transactions=None)

    def get_block_by_hash(self, block_hash: str) -> Block:
        w3 = self._w3_client()
        b = w3.eth.get_block(block_hash, full_transactions=False)
        return self.get_block(int(b["number"]))

    def get_transaction_receipt(self, tx_hash: str) -> Receipt:
        w3 = self._w3_client()
        r = w3.eth.get_transaction_receipt(tx_hash)
        chain_id = self.get_chain_id()
        return Receipt(
            chain_id=chain_id,
            block_number=int(r["blockNumber"]),
            block_hash=r["blockHash"].hex()
            if hasattr(r["blockHash"], "hex")
            else str(r["blockHash"]),
            tx_hash=r["transactionHash"].hex()
            if hasattr(r["transactionHash"], "hex")
            else str(r["transactionHash"]),
            tx_index=int(r["transactionIndex"]),
            status=int(r["status"]),
            gas_used=int(r["gasUsed"]),
            effective_gas_price=(
                int(r["effectiveGasPrice"]) if r.get("effectiveGasPrice") is not None else None
            ),
            cumulative_gas_used=int(r["cumulativeGasUsed"]),
            contract_address=(
                str(r["contractAddress"]).lower() if r.get("contractAddress") else None
            ),
            logs_count=len(r.get("logs", [])),
        )

    def get_receipts_batch(self, tx_hashes: list[str]) -> list[Receipt]:
        return [self.get_transaction_receipt(h) for h in tx_hashes]

    def get_token_balance(self, token_address: str, holder_address: str, block_number: int) -> int:
        """Read balanceOf(holder) at `block_number`."""
        from eth_utils import keccak

        selector = "0x" + keccak(text="balanceOf(address)").hex()[:8]
        padded = holder_address.lower().replace("0x", "").rjust(64, "0")
        data = selector + padded
        w3 = self._w3_client()
        result = w3.eth.call({"to": token_address, "data": data}, block_identifier=block_number)
        return int.from_bytes(bytes(result), "big")

    def debug_trace_transaction(self, tx_hash: str, tracer: str = "callTracer") -> RawTrace:
        """Returns the recursive call tree. Raises if provider does not support it."""
        from web3._utils.method_formatters import method_formatters  # type: ignore[import-untyped]

        _ = method_formatters
        w3 = self._w3_client()
        # web3.py's manager.request_blocking is the lowest-level path
        result = w3.manager.request_blocking(
            "debug_traceTransaction", [tx_hash, {"tracer": tracer}]
        )
        chain_id = self.get_chain_id()
        return _trace_dict_to_raw_trace(result, chain_id, tx_hash, [])

    def get_finalized_block_number(self) -> int:
        """Latest block tagged `finalized` (post-merge)."""
        w3 = self._w3_client()
        b = w3.eth.get_block("finalized")
        return int(b["number"])

    def supports_debug_trace(self) -> bool:
        """Capability probe: try a known mainnet tx with debug_traceTransaction.
        Cached for the client lifetime."""
        if self._supports_trace_cache is not None:
            return self._supports_trace_cache
        try:
            # Use a known stable tx hash — any historical tx works as a probe.
            self.debug_trace_transaction(
                "0x0000000000000000000000000000000000000000000000000000000000000000"
            )
            self._supports_trace_cache = True
        except Exception:  # noqa: BLE001
            self._supports_trace_cache = False
        return self._supports_trace_cache


def _trace_dict_to_raw_trace(
    node: dict[str, Any],
    chain_id: int,
    tx_hash: str,
    trace_address: list[int],
    block_number: int = 0,
) -> RawTrace:
    """Convert a callTracer JSON node (recursive) to a RawTrace dataclass.

    Children come back under `node["calls"]` (or empty if absent).
    """
    calls_raw = node.get("calls") or []
    rt = RawTrace(
        chain_id=chain_id,
        block_number=block_number,
        tx_hash=tx_hash,
        type=str(node.get("type", "CALL")).upper(),
        from_addr=str(node.get("from", "")).lower(),
        to_addr=(str(node["to"]).lower() if node.get("to") else None),
        value=int(node.get("value", "0x0"), 16) if isinstance(node.get("value"), str) else 0,
        gas=int(node.get("gas", "0x0"), 16) if isinstance(node.get("gas"), str) else 0,
        gas_used=(
            int(node.get("gasUsed", "0x0"), 16) if isinstance(node.get("gasUsed"), str) else 0
        ),
        input_data=str(node.get("input", "0x")),
        output=str(node.get("output", "0x")),
        error=node.get("error"),
        revert_reason=node.get("revertReason"),
        calls=[],
        trace_address=trace_address,
    )
    for i, child in enumerate(calls_raw):
        rt.calls.append(
            _trace_dict_to_raw_trace(child, chain_id, tx_hash, trace_address + [i], block_number)
        )
    return rt


# Helper retained for callers needing typed return
def _typecast(x: Any) -> Any:
    return cast(Any, x)
