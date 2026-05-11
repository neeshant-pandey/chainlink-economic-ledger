#!/usr/bin/env python
"""Compute the topic0 (event signature hash) for a canonical Solidity event.

Usage:
    uv run python scripts/compute_topic0.py 'Transfer(address,address,uint256)'
    uv run python scripts/compute_topic0.py 'Staked(address,uint256,uint256,uint256)'

The canonical form has no parameter names, no `indexed` keyword, and no spaces.
Non-canonical input is rejected — silently hashing the wrong string would
produce a wrong topic0 that ships into the event registry.
"""

from __future__ import annotations

import sys

from eth_utils.crypto import keccak


def _validate_canonical(signature: str) -> None:
    if " " in signature:
        raise ValueError(
            f"non-canonical signature {signature!r}: contains spaces "
            "(canonical form: 'Transfer(address,address,uint256)')"
        )
    if "indexed" in signature:
        raise ValueError(
            f"non-canonical signature {signature!r}: drop the 'indexed' keyword"
        )
    if "(" not in signature or not signature.endswith(")"):
        raise ValueError(f"non-canonical signature {signature!r}: expected EventName(types)")


def compute_topic0(canonical_signature: str) -> str:
    _validate_canonical(canonical_signature)
    return "0x" + keccak(text=canonical_signature).hex()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        print(compute_topic0(sys.argv[1]))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
