"""`debug_traceTransaction` fetching. Fetch only — decoding is in `decoder/trace_decoder.py`.

Trace fetching is expensive (10-100x a regular receipt). The pipeline does NOT trace
every tx; it traces only the txs that need internal-call reconciliation:
  - slashing transactions
  - migration transactions (v0.1 → v0.2)
  - any tx where logs alone produce an unmatched economic action
"""

from __future__ import annotations

from decoder.types import RawTrace
from ingestion.rpc.client import RpcClient


def fetch_trace(client: RpcClient, tx_hash: str) -> RawTrace:
    """Single-tx trace via `debug_traceTransaction` with `callTracer`."""
    return client.debug_trace_transaction(tx_hash)


def fetch_traces_for_txs(
    client: RpcClient,
    tx_hashes: list[str],
    parallelism: int = 4,
) -> dict[str, RawTrace]:
    """Sequential trace fetch (parallelism arg retained for API compat — the
    BQ-primary pipeline rarely uses RPC traces). Returns `{tx_hash: RawTrace}`.
    """
    _ = parallelism
    out: dict[str, RawTrace] = {}
    for tx_hash in tx_hashes:
        out[tx_hash] = fetch_trace(client, tx_hash)
    return out
