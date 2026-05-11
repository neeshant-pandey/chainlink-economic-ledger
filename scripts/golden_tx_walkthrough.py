"""Forensic decode of one tx, end-to-end.

Wires together: RPC fetch → event/trace decode → action classification →
movement build → reconciliation → ledger entries → pretty-printed walkthrough.

The local demo uses cached fixtures instead — see `make dbt-build-local`.
This script is the live-runtime entry point that requires an RPC endpoint.

Usage:
    python scripts/golden_tx_walkthrough.py 0x1234abcd...
"""

from __future__ import annotations

import sys


def walk(tx_hash: str) -> int:
    raise NotImplementedError(
        "Planned live walkthrough: the local demo uses cached golden fixture "
        "tests instead of fetching arbitrary transactions on demand."
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: golden_tx_walkthrough.py <tx_hash>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(walk(sys.argv[1]))
