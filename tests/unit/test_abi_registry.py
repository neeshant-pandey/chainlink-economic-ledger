"""Tests for `decoder.abi_registry`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from decoder.abi_registry import AbiRegistry, _ensure_no_overlap
from decoder.event_decoder import ERC20_TRANSFER_TOPIC0
from decoder.types import Abi, Phase


def test_load_from_config_validates_abi_files_present(tmp_path: Path) -> None:
    contracts_dir = tmp_path / "contracts"
    abis_dir = tmp_path / "abis"
    contracts_dir.mkdir()
    abis_dir.mkdir()
    (contracts_dir / "x.yaml").write_text(
        """
chain_id: 1
contracts:
  - role: foo
    address: "0xabc"
    deployed_block: 0
    phases:
      - abi_version: v1
        from_block: 0
        to_block: null
        abi_file: missing.json
"""
    )
    with pytest.raises(FileNotFoundError):
        AbiRegistry.load_from_config(str(contracts_dir), str(abis_dir))


def test_load_from_config_with_present_abi(tmp_path: Path) -> None:
    contracts_dir = tmp_path / "contracts"
    abis_dir = tmp_path / "abis"
    contracts_dir.mkdir()
    abis_dir.mkdir()
    (abis_dir / "foo.json").write_text(
        json.dumps([{"type": "event", "name": "Transfer", "inputs": []}])
    )
    (contracts_dir / "x.yaml").write_text(
        """
chain_id: 1
contracts:
  - role: foo
    address: "0xabc0000000000000000000000000000000000000"
    deployed_block: 0
    phases:
      - abi_version: v1
        from_block: 0
        to_block: null
        abi_file: foo.json
"""
    )
    reg = AbiRegistry.load_from_config(str(contracts_dir), str(abis_dir))
    assert "0xabc0000000000000000000000000000000000000" in reg.addresses()


def test_get_returns_phase_active_at_block() -> None:
    abi = Abi(abi_version="v1", json_abi=[])
    phase = Phase(
        contract_address="0xabc",
        abi_version="v1",
        from_block=100,
        to_block=200,
    )
    reg = AbiRegistry({"0xabc": [(phase, abi)]})
    assert reg.get("0xabc", 150) is abi


def test_get_raises_for_block_before_deployment() -> None:
    abi = Abi(abi_version="v1", json_abi=[])
    phase = Phase(
        contract_address="0xabc",
        abi_version="v1",
        from_block=100,
        to_block=200,
    )
    reg = AbiRegistry({"0xabc": [(phase, abi)]})
    with pytest.raises(KeyError):
        reg.get("0xabc", 50)


def test_get_raises_for_unknown_address() -> None:
    reg = AbiRegistry({})
    with pytest.raises(KeyError):
        reg.get("0xnotfound", 100)


def test_event_signature_matches_known_topic0() -> None:
    """ERC-20 Transfer signature is well-known."""
    abi = Abi(
        abi_version="erc20_v1",
        json_abi=[
            {
                "type": "event",
                "name": "Transfer",
                "inputs": [
                    {"name": "from", "type": "address", "indexed": True},
                    {"name": "to", "type": "address", "indexed": True},
                    {"name": "value", "type": "uint256", "indexed": False},
                ],
            }
        ],
    )
    sig = AbiRegistry.event_signature(abi, "Transfer")
    assert sig.lower() == ERC20_TRANSFER_TOPIC0


def test_method_selector_matches_known_erc20_transfer() -> None:
    abi = Abi(
        abi_version="erc20_v1",
        json_abi=[
            {
                "type": "function",
                "name": "transfer",
                "inputs": [
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                ],
                "outputs": [],
            }
        ],
    )
    sel = AbiRegistry.method_selector(abi, "transfer")
    assert sel == "0xa9059cbb"


def test_ensure_no_overlap_rejects_overlap() -> None:
    phases = [
        Phase("0xabc", "v1", 100, 200),
        Phase("0xabc", "v2", 150, 300),  # overlaps
    ]
    with pytest.raises(ValueError):
        _ensure_no_overlap(phases)
