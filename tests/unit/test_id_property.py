"""property-style sanity for every `compute_*_id` function.

For each ID function:
  (a) outputs are 64-char lowercase hex (sha256 hexdigest)
  (b) different inputs produce different outputs (no collisions in 5+ inputs)
  (c) same input produces same output (in-process determinism)

ID functions covered:
  - compute_raw_log_id              (decoder.event_decoder)
  - compute_decoded_event_id        (decoder.event_decoder)
  - compute_raw_trace_call_id       (decoder.trace_decoder)
  - compute_movement_id             (reconciliation.movement_builder)
  - compute_action_id               (protocols.staking_v02.semantics)
  - compute_ledger_entry_id         (protocols.staking_v02.ledger_builder)
  - compute_run_partition_id        (lineage.run_metadata)
  - compute_pa_action_id            (protocols.payment_abstraction.semantics)
  - compute_pa_ledger_entry_id      (protocols.payment_abstraction.ledger_builder)
"""

from __future__ import annotations

import pytest

from decoder.event_decoder import compute_decoded_event_id, compute_raw_log_id
from decoder.trace_decoder import compute_raw_trace_call_id
from decoder.types import DecodedEvent, RawLog
from lineage.run_metadata import compute_run_partition_id
from protocols.payment_abstraction.ledger_builder import compute_pa_ledger_entry_id
from protocols.payment_abstraction.semantics import (
    PAActionKind,
    compute_pa_action_id,
)
from protocols.staking_v02.ledger_builder import compute_ledger_entry_id
from protocols.staking_v02.semantics import ActionKind, compute_action_id
from reconciliation.movement_builder import compute_movement_id

_HEX = set("0123456789abcdef")


def _assert_sha256_hex(value: str) -> None:
    assert isinstance(value, str)
    assert len(value) == 64
    assert all(c in _HEX for c in value)


def _check_property(ids: list[str]) -> None:
    """(a) every id is 64-char lowercase hex; (b) all distinct."""
    for i in ids:
        _assert_sha256_hex(i)
    assert len(set(ids)) == len(ids), "expected zero collisions in sample"


def _raw_log(block_number: int = 18_000_000, log_index: int = 0) -> RawLog:
    return RawLog(
        chain_id=1,
        block_number=block_number,
        block_hash="0x" + "1" * 64,
        tx_hash="0x" + "2" * 64,
        tx_index=0,
        log_index=log_index,
        address="0x514910771af9ca656af840dff83e8264ecf986ca",
        topics=[
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
        ],
        data="0x" + "0" * 64,
    )


@pytest.mark.parametrize("seed", list(range(5)))
def test_compute_raw_log_id_property(seed: int) -> None:
    """Per-seed input -> 64-char hex; same input repeated -> same id."""
    log = _raw_log(block_number=18_000_000 + seed, log_index=seed)
    out1 = compute_raw_log_id(log)
    out2 = compute_raw_log_id(log)
    _assert_sha256_hex(out1)
    assert out1 == out2


def test_compute_raw_log_id_no_collisions_in_5_inputs() -> None:
    ids = [compute_raw_log_id(_raw_log(log_index=i)) for i in range(5)]
    _check_property(ids)


def _decoded_event(block_number: int, log_index: int) -> DecodedEvent:
    return DecodedEvent(
        raw_log_id="rl",
        decoded_event_id="",
        chain_id=1,
        block_number=block_number,
        tx_hash="0x" + "2" * 64,
        log_index=log_index,
        contract_address="0xa" * 20,
        event_name="Transfer",
        event_signature="0xddf252ad",
        indexed_params={},
        data_params={},
    )


@pytest.mark.parametrize("seed", list(range(5)))
def test_compute_decoded_event_id_property(seed: int) -> None:
    e = _decoded_event(18_000_000 + seed, seed)
    out1 = compute_decoded_event_id(e)
    out2 = compute_decoded_event_id(e)
    _assert_sha256_hex(out1)
    assert out1 == out2


def test_compute_decoded_event_id_no_collisions() -> None:
    ids = [compute_decoded_event_id(_decoded_event(18_000_000, i)) for i in range(5)]
    _check_property(ids)


@pytest.mark.parametrize(
    "trace_addr",
    [[], [0], [1], [0, 0], [0, 1], [1, 0]],
)
def test_compute_raw_trace_call_id_property(trace_addr: list[int]) -> None:
    tx = "0x" + "a" * 64
    out1 = compute_raw_trace_call_id(tx, trace_addr)
    out2 = compute_raw_trace_call_id(tx, trace_addr)
    _assert_sha256_hex(out1)
    assert out1 == out2


def test_compute_raw_trace_call_id_no_collisions() -> None:
    tx = "0x" + "b" * 64
    ids = [compute_raw_trace_call_id(tx, ta) for ta in ([], [0], [1], [0, 0], [0, 1], [1, 0])]
    _check_property(ids)


def test_compute_raw_trace_call_id_root_distinct_from_first_child() -> None:
    """Empty list and [0] must hash distinctly (per docstring)."""
    tx = "0x" + "c" * 64
    assert compute_raw_trace_call_id(tx, []) != compute_raw_trace_call_id(tx, [0])


@pytest.mark.parametrize("seed", list(range(5)))
def test_compute_movement_id_property(seed: int) -> None:
    out1 = compute_movement_id(1, "0xtx", "0xfr", "0xto", 100 + seed, seed)
    out2 = compute_movement_id(1, "0xtx", "0xfr", "0xto", 100 + seed, seed)
    _assert_sha256_hex(out1)
    assert out1 == out2


def test_compute_movement_id_no_collisions_over_amount() -> None:
    ids = [compute_movement_id(1, "0xt", "0xf", "0xto", i, 0) for i in range(5)]
    _check_property(ids)


def test_compute_movement_id_no_collisions_over_occurrence() -> None:
    ids = [compute_movement_id(1, "0xt", "0xf", "0xto", 100, i) for i in range(5)]
    _check_property(ids)


@pytest.mark.parametrize("seed", list(range(5)))
def test_compute_action_id_property(seed: int) -> None:
    e = _decoded_event(18_000_000 + seed, seed)
    e_with_id = DecodedEvent(
        raw_log_id=e.raw_log_id,
        decoded_event_id=compute_decoded_event_id(e),
        chain_id=e.chain_id,
        block_number=e.block_number,
        tx_hash=e.tx_hash,
        log_index=e.log_index,
        contract_address=e.contract_address,
        event_name=e.event_name,
        event_signature=e.event_signature,
        indexed_params=e.indexed_params,
        data_params=e.data_params,
    )
    out1 = compute_action_id(e_with_id, ActionKind.STAKE)
    out2 = compute_action_id(e_with_id, ActionKind.STAKE)
    _assert_sha256_hex(out1)
    assert out1 == out2


def test_compute_action_id_different_kinds_no_collision() -> None:
    e = _decoded_event(18_000_000, 0)
    e_with_id = DecodedEvent(
        raw_log_id=e.raw_log_id,
        decoded_event_id=compute_decoded_event_id(e),
        chain_id=e.chain_id,
        block_number=e.block_number,
        tx_hash=e.tx_hash,
        log_index=e.log_index,
        contract_address=e.contract_address,
        event_name=e.event_name,
        event_signature=e.event_signature,
        indexed_params=e.indexed_params,
        data_params=e.data_params,
    )
    ids = [
        compute_action_id(e_with_id, k)
        for k in (
            ActionKind.STAKE,
            ActionKind.UNSTAKE_REQUESTED,
            ActionKind.UNSTAKE_FINALIZED,
            ActionKind.REWARD_CLAIMED,
            ActionKind.SLASHED,
        )
    ]
    _check_property(ids)


@pytest.mark.parametrize("idx", list(range(5)))
def test_compute_ledger_entry_id_property(idx: int) -> None:
    out1 = compute_ledger_entry_id("action-abc", idx)
    out2 = compute_ledger_entry_id("action-abc", idx)
    _assert_sha256_hex(out1)
    assert out1 == out2


def test_compute_ledger_entry_id_distinct_entries_no_collision() -> None:
    ids = [compute_ledger_entry_id("a", i) for i in range(5)]
    _check_property(ids)


@pytest.mark.parametrize("run_idx", list(range(5)))
def test_compute_run_partition_id_property(run_idx: int) -> None:
    out1 = compute_run_partition_id(1, "dag", f"run{run_idx}", "src", "2026-05-11")
    out2 = compute_run_partition_id(1, "dag", f"run{run_idx}", "src", "2026-05-11")
    _assert_sha256_hex(out1)
    assert out1 == out2


def test_compute_run_partition_id_no_collisions() -> None:
    ids = [compute_run_partition_id(1, "dag", f"r{i}", "src", "2026-05-11") for i in range(5)]
    _check_property(ids)


# --- PA equivalents -------------------------------------------------------


def test_compute_pa_action_id_property() -> None:
    e = _decoded_event(18_000_000, 0)
    e_with_id = DecodedEvent(
        raw_log_id=e.raw_log_id,
        decoded_event_id=compute_decoded_event_id(e),
        chain_id=e.chain_id,
        block_number=e.block_number,
        tx_hash=e.tx_hash,
        log_index=e.log_index,
        contract_address=e.contract_address,
        event_name=e.event_name,
        event_signature=e.event_signature,
        indexed_params=e.indexed_params,
        data_params=e.data_params,
    )
    ids = [
        compute_pa_action_id(e_with_id, k)
        for k in (
            PAActionKind.FEE_RECEIVED,
            PAActionKind.SWAP_EXECUTED,
            PAActionKind.RESERVES_DEPOSIT,
            PAActionKind.SERVICE_FEE_FORWARDED,
            PAActionKind.CONFIG_CHANGED,
        )
    ]
    _check_property(ids)
    # Determinism: same inputs -> same id
    again = compute_pa_action_id(e_with_id, PAActionKind.FEE_RECEIVED)
    assert again == ids[0]


def test_compute_pa_ledger_entry_id_property() -> None:
    ids = [compute_pa_ledger_entry_id("act", i) for i in range(5)]
    _check_property(ids)
    # Determinism
    assert compute_pa_ledger_entry_id("act", 0) == ids[0]
