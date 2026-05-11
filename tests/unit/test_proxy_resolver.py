"""public-function coverage for `decoder/proxy_resolver.py`.

Every public function exercised:
  - storage_word_to_address
  - resolve_implementation_from_config
  - resolve_implementation_via_rpc (with a fake rpc_call)
  - is_eip1967_proxy_marker
  - derive_eip1967_slot
"""

from __future__ import annotations

import pytest

from decoder.proxy_resolver import (
    EIP1967_ADMIN_SLOT,
    EIP1967_BEACON_SLOT,
    EIP1967_IMPL_SLOT,
    derive_eip1967_slot,
    is_eip1967_proxy_marker,
    resolve_implementation_from_config,
    resolve_implementation_via_rpc,
    storage_word_to_address,
)
from decoder.types import Phase


def test_storage_word_to_address_extracts_last_20_bytes() -> None:
    """The address is right-aligned: bytes [12:32] are the 20-byte address."""
    impl = "0xabcdef0123456789abcdef0123456789abcdef01"
    word = "0x" + "0" * 24 + impl[2:]
    assert storage_word_to_address(word) == impl.lower()


def test_storage_word_to_address_rejects_wrong_length() -> None:
    with pytest.raises(ValueError):
        storage_word_to_address("0x1234")


def test_resolve_implementation_from_config_returns_lowercase() -> None:
    """The YAML may carry mixed-case; resolver normalizes to lowercase."""
    phase = Phase(
        contract_address="0xdeadbeef" + "0" * 32,
        abi_version="v1",
        from_block=0,
        to_block=None,
    )
    impl = resolve_implementation_from_config(
        phase, {"implementation_address": "0xabcdef0123456789abcdef0123456789abcdef01"}
    )
    assert impl == "0xabcdef0123456789abcdef0123456789abcdef01"


def test_resolve_implementation_from_config_returns_none_when_absent() -> None:
    """Missing implementation_address -> None."""
    phase = Phase(
        contract_address="0x0",
        abi_version="v1",
        from_block=0,
        to_block=None,
    )
    assert resolve_implementation_from_config(phase, {"abi_version": "v1"}) is None


def test_resolve_implementation_via_rpc_returns_impl_when_slot_populated() -> None:
    """A non-zero word at the impl slot decodes to a lowercase address."""
    impl = "0xabcdef0123456789abcdef0123456789abcdef01"
    impl_word = "0x" + "0" * 24 + impl[2:]

    def rpc_call(addr: str, slot: str, block: str) -> str:
        # Verify the call shape matches the spec
        assert slot.lower() == EIP1967_IMPL_SLOT
        return impl_word

    out = resolve_implementation_via_rpc(rpc_call, "0xPROXY" + "0" * 35, 18_000_000)
    assert out == impl


def test_resolve_implementation_via_rpc_returns_beacon_when_no_direct_impl() -> None:
    """If the impl slot is zero but the beacon slot is non-zero, return beacon
    (caller decides whether to follow). This documents the fallback shape."""
    beacon = "0xbeefcafe" + "0" * 32
    beacon_word = "0x" + "0" * 24 + beacon[2:]

    def rpc_call(addr: str, slot: str, block: str) -> str:
        if slot.lower() == EIP1967_IMPL_SLOT:
            return "0x" + "0" * 64  # zero -> not a direct impl proxy
        if slot.lower() == EIP1967_BEACON_SLOT:
            return beacon_word
        return "0x" + "0" * 64

    out = resolve_implementation_via_rpc(rpc_call, "0xPROXY" + "0" * 35, 18_000_000)
    assert out == beacon


def test_resolve_implementation_via_rpc_returns_none_when_all_slots_zero() -> None:
    """If neither slot is populated, this is not a proxy -> None."""

    def rpc_call(addr: str, slot: str, block: str) -> str:
        return "0x" + "0" * 64

    assert resolve_implementation_via_rpc(rpc_call, "0x0", 1) is None


def test_is_eip1967_proxy_marker_true_for_non_zero_word() -> None:
    """Word containing any non-zero hex digit is a valid marker."""
    impl_word = "0x" + "0" * 24 + "abcdef0123456789abcdef0123456789abcdef01"
    assert is_eip1967_proxy_marker(impl_word) is True


def test_is_eip1967_proxy_marker_false_for_zero_word() -> None:
    """All-zeros means slot empty, not a proxy."""
    zero = "0x" + "0" * 64
    assert is_eip1967_proxy_marker(zero) is False


def test_is_eip1967_proxy_marker_false_for_malformed_input() -> None:
    """Wrong length -> False (not a valid storage word)."""
    assert is_eip1967_proxy_marker("0xabc") is False


def test_derive_eip1967_slot_matches_constant() -> None:
    """The derived slot for the canonical label matches the documented constant."""
    derived = derive_eip1967_slot("eip1967.proxy.implementation")
    assert derived.lower() == EIP1967_IMPL_SLOT
    # Also verify the admin / beacon slot constants are well-formed 32-byte hex
    assert len(EIP1967_ADMIN_SLOT) == 66
    assert len(EIP1967_BEACON_SLOT) == 66


def test_derive_eip1967_slot_changes_with_label() -> None:
    """Different labels produce different slots."""
    a = derive_eip1967_slot("eip1967.proxy.implementation")
    b = derive_eip1967_slot("eip1967.proxy.beacon")
    c = derive_eip1967_slot("eip1967.proxy.admin")
    assert len({a, b, c}) == 3
