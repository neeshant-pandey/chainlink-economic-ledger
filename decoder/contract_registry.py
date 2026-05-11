"""Contract metadata registry. Companion to `AbiRegistry` — knows which contracts
exist, their roles, deploy blocks, and phase boundaries.

Loaded from `config/contracts/{staking_v02,payment_abstraction,link_token}.yaml`.
Read-only post-load: phase changes are deploy-time, tracked in git.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self

import yaml

from decoder.types import ContractMeta, Phase


class ContractRegistry:
    """Indexed by lowercase address. Pure lookups after `load`; no I/O."""

    def __init__(self, by_address: dict[str, ContractMeta]) -> None:
        self._by_address = by_address

    @classmethod
    def load(cls, contracts_dir: str) -> Self:
        """Loads every YAML in the directory. Validates non-overlapping phases
        and that every phase has a corresponding ABI file (the ABI file check
        is delegated to `AbiRegistry.load_from_config`)."""
        contracts_path = Path(contracts_dir)
        by_address: dict[str, ContractMeta] = {}

        for yaml_file in sorted(contracts_path.glob("*.yaml")):
            with yaml_file.open("r") as f:
                doc = yaml.safe_load(f) or {}
            for contract in doc.get("contracts", []):
                address = str(contract["address"]).lower()
                role = str(contract.get("role", yaml_file.stem))
                deploy_block = int(contract.get("deployed_block", 0))
                phases = [
                    Phase(
                        contract_address=address,
                        abi_version=str(p["abi_version"]),
                        from_block=int(p["from_block"]),
                        to_block=(int(p["to_block"]) if p.get("to_block") is not None else None),
                    )
                    for p in contract.get("phases", [])
                ]
                cls._validate_phases(address, phases)
                by_address[address] = ContractMeta(
                    contract_address=address,
                    role=role,
                    deployed_block=deploy_block,
                    phases=phases,
                )
        return cls(by_address=by_address)

    @staticmethod
    def _validate_phases(address: str, phases: list[Phase]) -> None:
        """Reject overlapping or out-of-order phases. Helper kept private —
        users should never need to call it directly."""
        sorted_phases = sorted(phases, key=lambda p: p.from_block)
        for prev, curr in zip(sorted_phases, sorted_phases[1:], strict=False):
            prev_end = prev.to_block if prev.to_block is not None else float("inf")
            if isinstance(prev_end, float):
                # an open-ended phase cannot be followed by another phase
                raise ValueError(
                    f"phase overlap for {address}: "
                    f"{prev.abi_version} is open-ended but {curr.abi_version} follows"
                )
            if prev_end >= curr.from_block:
                raise ValueError(
                    f"overlapping phases for {address}: "
                    f"{prev.abi_version} ends at {prev_end}, "
                    f"{curr.abi_version} starts at {curr.from_block}"
                )

    def list_active(self, block_number: int) -> list[ContractMeta]:
        """All known contracts whose deploy_block <= block_number and that have
        at least one phase active at block_number."""
        out: list[ContractMeta] = []
        for meta in self._by_address.values():
            if meta.deployed_block > block_number:
                continue
            for phase in meta.phases:
                if phase.from_block <= block_number and (
                    phase.to_block is None or block_number <= phase.to_block
                ):
                    out.append(meta)
                    break
        return out

    def get_phase(self, contract_address: str, block_number: int) -> Phase:
        """Returns the phase active for `contract_address` at `block_number`.
        Raises `KeyError` if no phase covers the block."""
        addr = contract_address.lower()
        if addr not in self._by_address:
            raise KeyError(f"contract {addr!r} not registered")
        for phase in self._by_address[addr].phases:
            if phase.from_block <= block_number and (
                phase.to_block is None or block_number <= phase.to_block
            ):
                return phase
        raise KeyError(f"no phase covers block {block_number} for {addr!r}")

    def is_known(self, address: str) -> bool:
        """True iff `address` (case-insensitive) is registered."""
        return address.lower() in self._by_address

    def role(self, address: str) -> str | None:
        """Returns the role string from contract YAML (e.g.
        `staking_pool_v02`, `pa_reserves`). None if address not registered."""
        meta = self._by_address.get(address.lower())
        return meta.role if meta else None

    def addresses(self) -> list[str]:
        """All registered lowercase addresses, in load order. Convenience for
        the BQ extractor's `IN UNNEST(@addresses)` predicates."""
        return list(self._by_address.keys())
