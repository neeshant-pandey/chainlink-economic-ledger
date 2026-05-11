"""Tests for `decoder.contract_registry`."""

from __future__ import annotations

from pathlib import Path

import pytest

from decoder.contract_registry import ContractRegistry


def _write_yaml(tmp_path: Path, content: str) -> Path:
    contracts_dir = tmp_path / "contracts"
    contracts_dir.mkdir(exist_ok=True)
    (contracts_dir / "test.yaml").write_text(content)
    return contracts_dir


def test_load_validates_non_overlapping_phases(tmp_path: Path) -> None:
    contracts_dir = _write_yaml(
        tmp_path,
        """
chain_id: 1
contracts:
  - role: foo
    address: "0xabc"
    deployed_block: 0
    phases:
      - abi_version: v1
        from_block: 100
        to_block: 200
      - abi_version: v2
        from_block: 150
        to_block: 300
""",
    )
    with pytest.raises(ValueError):
        ContractRegistry.load(str(contracts_dir))


def test_list_active_filters_by_block(tmp_path: Path) -> None:
    contracts_dir = _write_yaml(
        tmp_path,
        """
chain_id: 1
contracts:
  - role: foo
    address: "0xabc"
    deployed_block: 100
    phases:
      - abi_version: v1
        from_block: 100
        to_block: 200
""",
    )
    reg = ContractRegistry.load(str(contracts_dir))
    assert len(reg.list_active(150)) == 1
    assert len(reg.list_active(50)) == 0  # before deploy
    assert len(reg.list_active(250)) == 0  # after end


def test_get_phase_raises_for_uncovered_block(tmp_path: Path) -> None:
    contracts_dir = _write_yaml(
        tmp_path,
        """
chain_id: 1
contracts:
  - role: foo
    address: "0xabc"
    deployed_block: 100
    phases:
      - abi_version: v1
        from_block: 100
        to_block: 200
""",
    )
    reg = ContractRegistry.load(str(contracts_dir))
    with pytest.raises(KeyError):
        reg.get_phase("0xabc", 50)


def test_role_returns_yaml_role(tmp_path: Path) -> None:
    contracts_dir = _write_yaml(
        tmp_path,
        """
chain_id: 1
contracts:
  - role: community_staking_pool
    address: "0xabcdef0000000000000000000000000000000000"
    deployed_block: 100
    phases:
      - abi_version: v0.2.0
        from_block: 100
        to_block: null
""",
    )
    reg = ContractRegistry.load(str(contracts_dir))
    assert reg.role("0xabcdef0000000000000000000000000000000000") == "community_staking_pool"
    assert reg.role("0xnotregistered") is None
    assert reg.is_known("0xabcdef0000000000000000000000000000000000")
