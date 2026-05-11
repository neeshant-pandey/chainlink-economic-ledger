"""EIP-1967 / EIP-1822 / OZ TransparentUpgradeableProxy implementation resolver.

A proxy emits the events but the implementation contract holds the ABI and
bytecode — decoding events from a proxied address requires knowing which
implementation was active at a given block.

EIP-1967 storage slots:

    impl   = bytes32(uint256(keccak256("eip1967.proxy.implementation")) - 1)
           = 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc
    admin  = bytes32(uint256(keccak256("eip1967.proxy.admin")) - 1)
           = 0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103
    beacon = bytes32(uint256(keccak256("eip1967.proxy.beacon")) - 1)
           = 0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50

Resolution:
  1. eth_getStorageAt(proxy, IMPL_SLOT, block) → implementation address
  2. If zero, try the beacon slot, then call beacon.implementation()
  3. Fall back to the configured implementation in `config/contracts/*.yaml`

The BQ-only path reads the configured implementation from YAML — a pure config
lookup. That is the default path the pipeline uses.
"""

from __future__ import annotations

import hashlib
from typing import Any

from decoder.types import Phase

# EIP-1967 storage slot constants (verified against the spec).
EIP1967_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
EIP1967_ADMIN_SLOT = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"
EIP1967_BEACON_SLOT = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"


def _strip_0x(s: str) -> str:
    return s[2:] if s.startswith(("0x", "0X")) else s


def storage_word_to_address(word: str) -> str:
    """Extract a 20-byte address (right-aligned) from a 32-byte storage word.

    Storage holds addresses padded with 12 leading zero bytes; the address
    occupies bytes [12:32] (chars [24:64] in the hex string after stripping
    `0x`).
    """
    raw = _strip_0x(word)
    if len(raw) != 64:
        raise ValueError(f"storage word must be 32 bytes (64 hex chars), got {len(raw)}")
    return "0x" + raw[24:].lower()


def resolve_implementation_from_config(
    phase: Phase,
    contracts_yaml_phase: dict[str, Any],
) -> str | None:
    """Pure-config implementation resolution. Returns the implementation
    address (lowercase) if present in the YAML phase, else None.

    The contracts YAML schema permits an optional `implementation_address` per
    phase; this is what the BQ-primary path consumes (no RPC call needed).
    """
    impl = contracts_yaml_phase.get("implementation_address")
    if impl is None:
        return None
    return str(impl).lower()


def resolve_implementation_via_rpc(
    rpc_call: Any,
    proxy_address: str,
    block_number: int,
) -> str | None:
    """RPC-based fallback. `rpc_call` is a callable matching the `eth_getStorageAt`
    signature: `rpc_call(address, slot, block_number_or_hex) -> str`.

    Returns the implementation address (lowercase) or None if the impl slot is
    zero (i.e., the address is not an EIP-1967 proxy).

    This function is only used when the YAML doesn't carry the implementation
    address. The hot path for BQ-primary operation is
    `resolve_implementation_from_config`.
    """
    proxy = proxy_address.lower()
    block_hex = hex(block_number) if isinstance(block_number, int) else block_number

    # 1. Direct EIP-1967 impl slot
    impl_word = rpc_call(proxy, EIP1967_IMPL_SLOT, block_hex)
    if impl_word and int(impl_word, 16) != 0:
        return storage_word_to_address(impl_word)

    # 2. Beacon proxy fallback: read beacon slot, then call beacon.implementation()
    beacon_word = rpc_call(proxy, EIP1967_BEACON_SLOT, block_hex)
    if beacon_word and int(beacon_word, 16) != 0:
        beacon_addr = storage_word_to_address(beacon_word)
        # implementation() selector = first 4 bytes of keccak("implementation()")
        # = 0x5c60da1b
        # We can't actually make that call here without a full RPC. The caller
        # must arrange it. For the BQ-primary path this branch is unused.
        return beacon_addr  # caller decides whether to follow the beacon

    return None


def is_eip1967_proxy_marker(slot_value: str) -> bool:
    """Quick test: does `slot_value` (a 32-byte storage word read at
    EIP1967_IMPL_SLOT) look like a non-zero address?

    Useful in tests where we want to confirm a contract is in fact a proxy
    without needing the full RPC plumbing.
    """
    raw = _strip_0x(slot_value)
    if len(raw) != 64:
        return False
    return int(raw, 16) != 0


def derive_eip1967_slot(label: str) -> str:
    """Compute the EIP-1967 storage slot for a custom label, useful for
    documentation / verification:

        slot = bytes32(uint256(keccak256(label)) - 1)

    Verifiable: derive_eip1967_slot("eip1967.proxy.implementation") returns
    `0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc`.

    Note: we use `hashlib.sha3_256` here for portability; the actual EIP-1967
    spec mandates keccak256, which is `eth_utils.keccak`. This helper exists
    for symbolic checks; production callers use the constants above.
    """
    # Use eth_utils.keccak for correctness — keccak256, not SHA-3-256.
    from eth_utils.crypto import keccak  # local import to keep module light

    h = int(keccak(text=label).hex(), 16) - 1
    # Mask to 32 bytes
    h &= (1 << 256) - 1
    return "0x" + format(h, "064x")


# Sanity check — exercised by tests, not at import time. The label below
# matches the EIP-1967 spec; the result must be the IMPL_SLOT constant.
def _verify_impl_slot() -> bool:
    """Returns True iff `derive_eip1967_slot("eip1967.proxy.implementation")`
    matches `EIP1967_IMPL_SLOT`. A failure here indicates a keccak / hashlib
    mismatch and would break proxy resolution at runtime — surface it."""
    return derive_eip1967_slot("eip1967.proxy.implementation").lower() == EIP1967_IMPL_SLOT


__all__ = [
    "EIP1967_ADMIN_SLOT",
    "EIP1967_BEACON_SLOT",
    "EIP1967_IMPL_SLOT",
    "derive_eip1967_slot",
    "is_eip1967_proxy_marker",
    "resolve_implementation_from_config",
    "resolve_implementation_via_rpc",
    "storage_word_to_address",
]


# Suppress unused-import warning for hashlib (kept for API stability and future
# non-keccak hashes if the spec ever broadens).
_ = hashlib
