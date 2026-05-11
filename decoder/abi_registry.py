"""Versioned ABI registry. Loaded once from `config/contracts/*.yaml` + `config/abis/*.json`.

Phases are config-driven; there is no runtime `register_phase()` API. Adding a
phase = editing a YAML and committing it. Selectors and topic0 are computed via
`eth_utils.keccak`; web3.py is deliberately avoided to keep the decoder's
dependency surface minimal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Self, cast

import yaml
from eth_utils.crypto import keccak

from decoder.types import Abi, Phase


def _canonical_event_signature(event: dict[str, Any]) -> str:
    """`Name(type1,type2,...)` — the input string for keccak."""
    inputs = event.get("inputs", [])
    types = ",".join(_canonical_type(i) for i in inputs)
    return f"{event['name']}({types})"


def _canonical_method_signature(method: dict[str, Any]) -> str:
    inputs = method.get("inputs", [])
    types = ",".join(_canonical_type(i) for i in inputs)
    return f"{method['name']}({types})"


def _canonical_type(input_def: dict[str, Any]) -> str:
    """Resolve `tuple`/`tuple[]` types into their parenthesized component form.

    Plain types (uint256, address, bytes32, ...) are returned as-is.
    """
    t = str(input_def["type"])
    if t.startswith("tuple"):
        components = input_def.get("components", [])
        inner = ",".join(_canonical_type(c) for c in components)
        # tuple[N] suffix preservation
        suffix = t[len("tuple") :]
        return f"({inner}){suffix}"
    return t


class AbiRegistry:
    """Maps `(contract_address, block_number)` → Abi. Immutable post-load."""

    def __init__(
        self,
        phases_by_address: dict[str, list[tuple[Phase, Abi]]],
    ) -> None:
        self._phases_by_address = phases_by_address

    @classmethod
    def load_from_config(cls, contracts_dir: str, abis_dir: str) -> Self:
        """Loads contract metadata from `contracts_dir/*.yaml` and ABI JSON from
        `abis_dir/`. Validates that every (contract_address, phase.abi_version)
        maps to a present ABI file. Raises on missing entries — fail-fast at
        boot.

        Layout expected:
            contracts_dir/staking_v02.yaml         (per the config-driven phase invariant schema)
            abis_dir/staking_pool.json
            abis_dir/link_token.json

        The ABI filename inside `abis_dir` is taken from the contract YAML's
        `abi_file` key on each phase, or defaults to `<role>.json`.
        """
        contracts_path = Path(contracts_dir)
        abis_path = Path(abis_dir)
        phases_by_address: dict[str, list[tuple[Phase, Abi]]] = {}

        for yaml_file in sorted(contracts_path.glob("*.yaml")):
            with yaml_file.open("r") as f:
                doc = yaml.safe_load(f) or {}
            for contract in doc.get("contracts", []):
                address = str(contract["address"]).lower()
                role = contract.get("role", yaml_file.stem)
                phases_list: list[tuple[Phase, Abi]] = []
                for phase_def in contract.get("phases", []):
                    phase = Phase(
                        contract_address=address,
                        abi_version=str(phase_def["abi_version"]),
                        from_block=int(phase_def["from_block"]),
                        to_block=(
                            int(phase_def["to_block"])
                            if phase_def.get("to_block") is not None
                            else None
                        ),
                    )
                    abi_file_name = phase_def.get("abi_file") or f"{role}.json"
                    abi_path = abis_path / abi_file_name
                    if not abi_path.exists():
                        raise FileNotFoundError(
                            f"ABI file '{abi_path}' missing for {address}@{phase.abi_version}"
                        )
                    with abi_path.open("r") as af:
                        json_abi = json.load(af)
                    abi = Abi(abi_version=phase.abi_version, json_abi=json_abi)
                    phases_list.append((phase, abi))
                phases_by_address[address] = phases_list

        return cls(phases_by_address=phases_by_address)

    def get(self, contract_address: str, block_number: int) -> Abi:
        """Returns the ABI active for `contract_address` at `block_number`.
        Raises `KeyError` if the address is not in the registry, or if no phase
        covers the block (e.g., a log from before the contract was deployed).
        """
        addr = contract_address.lower()
        if addr not in self._phases_by_address:
            raise KeyError(f"address {addr!r} not in ABI registry")
        for phase, abi in self._phases_by_address[addr]:
            if block_number < phase.from_block:
                continue
            if phase.to_block is not None and block_number > phase.to_block:
                continue
            return abi
        raise KeyError(f"no ABI phase covers block {block_number} for address {addr!r}")

    @staticmethod
    def event_signature(abi: Abi, event_name: str) -> str:
        """topic0: keccak256 of the canonical event signature, hex-encoded with
        leading 0x.
        """
        for entry in abi.json_abi:
            if entry.get("type") == "event" and entry.get("name") == event_name:
                sig = _canonical_event_signature(entry)
                return "0x" + keccak(text=sig).hex()
        raise KeyError(f"event {event_name!r} not in ABI {abi.abi_version}")

    @staticmethod
    def method_selector(abi: Abi, method_name: str) -> str:
        """First 4 bytes of keccak256 of the method signature, hex-encoded
        with leading 0x. Width is exactly 10 chars (0x + 8 hex)."""
        for entry in abi.json_abi:
            if entry.get("type") == "function" and entry.get("name") == method_name:
                sig = _canonical_method_signature(entry)
                return "0x" + keccak(text=sig).hex()[:8]
        raise KeyError(f"method {method_name!r} not in ABI {abi.abi_version}")

    def addresses(self) -> list[str]:
        """All registered (lowercase) contract addresses. Read-only utility."""
        return list(self._phases_by_address.keys())

    def phases(self, contract_address: str) -> list[Phase]:
        """All phases registered for an address, in load order."""
        addr = contract_address.lower()
        if addr not in self._phases_by_address:
            return []
        return [phase for phase, _ in self._phases_by_address[addr]]


def _ensure_no_overlap(phases: list[Phase]) -> None:
    """Validate that phases for the same address do not overlap. Helper exposed
    for tests."""
    sorted_phases = sorted(phases, key=lambda p: p.from_block)
    for prev, curr in zip(sorted_phases, sorted_phases[1:], strict=False):
        prev_end = prev.to_block if prev.to_block is not None else float("inf")
        if cast(float, prev_end) >= curr.from_block:
            raise ValueError(
                f"overlapping phases for {curr.contract_address}: "
                f"{prev.abi_version} ends at {prev_end}, "
                f"{curr.abi_version} starts at {curr.from_block}"
            )
