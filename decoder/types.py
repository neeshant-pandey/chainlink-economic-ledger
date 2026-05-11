"""Canonical typed objects shared across all modules.

Function signatures elsewhere reference these names — do not add or rename
fields without updating all consumers. The seven `compute_*_id` functions
(`raw_log_id`, `decoded_event_id`, `raw_trace_call_id`, `movement_id`,
`action_id`, `ledger_entry_id`, `run_partition_id`) are the idempotency contract.
See `docs/architecture.md#idempotency-grains` for the full table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Raw EVM artifacts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BlockHeader:
    chain_id: int
    block_number: int
    block_hash: str
    parent_hash: str
    timestamp: int  # unix seconds
    miner: str | None
    base_fee_per_gas: int | None


@dataclass(frozen=True)
class Block:
    header: BlockHeader
    transaction_hashes: list[str]
    full_transactions: list[Transaction] | None  # populated only when fetched with full_txs=True


@dataclass(frozen=True)
class Transaction:
    chain_id: int
    block_number: int
    block_hash: str
    tx_hash: str
    tx_index: int
    from_addr: str
    to_addr: str | None
    value: int
    input_data: str  # hex calldata
    gas: int
    gas_price: int | None
    max_fee_per_gas: int | None
    max_priority_fee_per_gas: int | None
    nonce: int


@dataclass(frozen=True)
class Receipt:
    chain_id: int
    block_number: int
    block_hash: str
    tx_hash: str
    tx_index: int
    status: int  # 0 = reverted, 1 = success
    gas_used: int
    effective_gas_price: int | None
    cumulative_gas_used: int
    contract_address: str | None
    logs_count: int


@dataclass(frozen=True)
class RawLog:
    chain_id: int
    block_number: int
    block_hash: str
    tx_hash: str
    tx_index: int
    log_index: int
    address: str
    topics: list[str]  # hex topic0..topic3
    data: str  # hex


@dataclass(frozen=True)
class RawTrace:
    """Top-level trace returned by debug_traceTransaction with `callTracer`.

    Recursive: each call may contain `calls`. `trace_address` is the path from root
    expressed as a list of indices, e.g. [0, 2, 1] = root.calls[0].calls[2].calls[1].
    """

    chain_id: int
    block_number: int
    tx_hash: str
    type: str  # CALL, CALLCODE, DELEGATECALL, STATICCALL, CREATE, etc.
    from_addr: str
    to_addr: str | None
    value: int
    gas: int
    gas_used: int
    input_data: str
    output: str
    error: str | None
    revert_reason: str | None
    calls: list[RawTrace] = field(default_factory=list)
    trace_address: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class TokenBalance:
    chain_id: int
    block_number: int
    token_address: str
    holder_address: str
    balance: int  # raw uint256


# ---------------------------------------------------------------------------
# Decoded artifacts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecodedEvent:
    raw_log_id: str
    decoded_event_id: str
    chain_id: int
    block_number: int
    tx_hash: str
    log_index: int
    contract_address: str
    event_name: str
    event_signature: str  # topic0
    indexed_params: dict[str, Any]
    data_params: dict[str, Any]


@dataclass(frozen=True)
class DecodedCall:
    raw_trace_call_id: str
    chain_id: int
    block_number: int
    tx_hash: str
    trace_address: list[int]
    contract_address: str | None
    method_name: str
    method_selector: str
    params: dict[str, Any]
    success: bool
    parent_success: bool


@dataclass(frozen=True)
class TraceTokenCall:
    """A successful internal ERC-20 transfer call observed in trace output."""

    raw_trace_call_id: str
    chain_id: int
    block_number: int
    tx_hash: str
    trace_address: list[int]
    token_address: str
    method_name: Literal["transfer", "transferFrom"]
    from_addr: str
    to_addr: str
    amount: int


# ---------------------------------------------------------------------------
# Decode results (structured failures)
# ---------------------------------------------------------------------------


DecodeFailureReason = Literal[
    "unknown_topic",
    "abi_mismatch",
    "malformed_data",
    "unregistered_contract",
    "phase_not_found",
]


@dataclass(frozen=True)
class DecodeResult:
    """Output of a single decode attempt. Either `decoded` is populated or a
    structured `failure_reason` is. `raw_log_id` (or equivalent raw id) is always
    populated so failures are joinable to raw artifacts."""

    raw_id: str  # raw_log_id or raw_trace_call_id
    success: bool
    decoded: DecodedEvent | DecodedCall | None
    failure_reason: DecodeFailureReason | None
    failure_detail: str | None  # free text, e.g. exception message


# ---------------------------------------------------------------------------
# Contract registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Phase:
    """A versioned ABI binding for a contract over a block range.

    Aggregator proxies / staking pool upgrades are modeled as a sequence of phases
    keyed by `(contract_address, abi_version, from_block, to_block)`.
    """

    contract_address: str
    abi_version: str
    from_block: int
    to_block: int | None  # None = open-ended


@dataclass(frozen=True)
class ContractMeta:
    contract_address: str
    role: str  # e.g. "staking_pool_v02", "reward_vault", "link_token"
    deployed_block: int
    phases: list[Phase]


@dataclass(frozen=True)
class Abi:
    """Minimal ABI projection sufficient for decoding. Wraps the JSON ABI for
    library consumption (web3.py / eth-abi); concrete shape left to the implementer."""

    abi_version: str
    json_abi: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Reorg model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReorgEvent:
    chain_id: int
    block_number: int
    old_block_hash: str
    new_block_hash: str
    detected_at: int  # unix seconds


@dataclass(frozen=True)
class PromotionResult:
    chain_id: int
    promoted_from_block: int
    promoted_to_block: int
    promoted_count: int
    conflicts: list[ReorgEvent]


# ---------------------------------------------------------------------------
# Storage results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WriteResult:
    gcs_path: str
    rows: int
    bytes_written: int
    run_partition_id: str


@dataclass(frozen=True)
class LoadResult:
    table: str
    rows_loaded: int
    bytes_loaded: int


@dataclass(frozen=True)
class MergeResult:
    target_table: str
    rows_inserted: int
    rows_updated: int
    rows_deleted: int


# ---------------------------------------------------------------------------
# Manifest / lineage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceRecord:
    run_id: str
    source_name: str
    chain_id: int
    partition_key: str
    gcs_paths: list[str]
    rows: int
    watermark_block: int


@dataclass(frozen=True)
class RunLineage:
    run_id: str
    dag_id: str
    sources: list[SourceRecord]
    manifest_ids: list[str]
    started_at: int
    completed_at: int | None


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayResult:
    chain_id: int
    from_block: int
    to_block: int
    new_run_partition_id: str
    raw_rows_deleted: int
    raw_rows_reingested: int
    marts_hash_stable: bool
    mismatched_marts: list[str]
