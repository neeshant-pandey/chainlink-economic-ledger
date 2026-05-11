"""Windowed log fetching with adaptive backoff.

Most RPC providers cap `eth_getLogs` results (Alchemy: 10k logs/2k blocks, Infura:
similar). On `query returned more than X results` errors, the adaptive fetcher
halves the window and retries.
"""

from __future__ import annotations

from collections.abc import Iterator

from decoder.types import RawLog
from ingestion.rpc.client import RpcClient


def fetch_logs_windowed(
    client: RpcClient,
    address: str | list[str],
    topics: list[str | list[str] | None],
    from_block: int,
    to_block: int,
    window_size: int,
) -> Iterator[list[RawLog]]:
    """Yields successive windows of logs. Caller is responsible for partition
    writes after each yield. Window is `window_size` blocks (inclusive)."""
    cur = from_block
    while cur <= to_block:
        end = min(cur + window_size - 1, to_block)
        yield client.get_logs(address, topics, cur, end)
        cur = end + 1


def fetch_logs_with_adaptive_window(
    client: RpcClient,
    address: str | list[str],
    topics: list[str | list[str] | None],
    from_block: int,
    to_block: int,
    initial_window: int = 2000,
    min_window: int = 32,
) -> list[RawLog]:
    """Halves window on RPC overflow errors; raises if `min_window` would be
    violated. Returns the full result set."""
    out: list[RawLog] = []
    window = initial_window
    cur = from_block
    while cur <= to_block:
        end = min(cur + window - 1, to_block)
        try:
            out.extend(client.get_logs(address, topics, cur, end))
            cur = end + 1
        except Exception:  # noqa: BLE001
            window //= 2
            if window < min_window:
                raise
    return out
