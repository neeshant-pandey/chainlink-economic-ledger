"""Tests for `reconciliation.movement_builder`."""

from __future__ import annotations

import hashlib

import pytest

from decoder.types import DecodedEvent, TraceTokenCall
from reconciliation.movement_builder import (
    TokenMovement,
    build_movements_from_trace_calls,
    build_movements_from_transfer_logs,
    compute_movement_id,
    unify_movements,
)


def _link_transfer_event(amount: int = 100, log_index: int = 0) -> DecodedEvent:
    return DecodedEvent(
        raw_log_id=f"raw|{log_index}",
        decoded_event_id=f"decoded|{log_index}",
        chain_id=1,
        block_number=18_000_000,
        tx_hash="0x" + "a" * 64,
        log_index=log_index,
        contract_address="0x514910771af9ca656af840dff83e8264ecf986ca",
        event_name="Transfer",
        event_signature="0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
        indexed_params={"from": "0x" + "11" * 20, "to": "0x" + "22" * 20},
        data_params={"value": amount},
    )


def _trace_token_call(amount: int = 100, trace_address: list[int] | None = None) -> TraceTokenCall:
    return TraceTokenCall(
        raw_trace_call_id=f"trace|{trace_address}",
        chain_id=1,
        block_number=18_000_000,
        tx_hash="0x" + "a" * 64,
        trace_address=trace_address or [0, 1],
        token_address="0x514910771af9ca656af840dff83e8264ecf986ca",
        method_name="transfer",
        from_addr="0x" + "11" * 20,
        to_addr="0x" + "22" * 20,
        amount=amount,
    )


def test_build_movements_from_transfer_logs() -> None:
    ev = _link_transfer_event(amount=100)
    movements = build_movements_from_transfer_logs([ev])
    assert len(movements) == 1
    m = movements[0]
    assert isinstance(m, TokenMovement)
    assert m.source_priority == "log"
    assert m.amount == 100
    assert ev.raw_log_id in m.evidence_ids


def test_build_movements_from_transfer_logs_skips_non_transfer() -> None:
    """Events whose signature is NOT the ERC-20 Transfer topic0 are skipped."""
    ev = _link_transfer_event()
    other_event = DecodedEvent(
        raw_log_id="other",
        decoded_event_id="other_d",
        chain_id=ev.chain_id,
        block_number=ev.block_number,
        tx_hash=ev.tx_hash,
        log_index=ev.log_index + 1,
        contract_address=ev.contract_address,
        event_name="SomethingElse",
        event_signature="0xff" * 32,  # not the Transfer sig
        indexed_params={"from": "0x" + "33" * 20, "to": "0x" + "44" * 20},
        data_params={"value": 99},
    )
    movements = build_movements_from_transfer_logs([ev, other_event])
    assert len(movements) == 1


def test_build_movements_from_trace_calls() -> None:
    call = _trace_token_call()
    movements = build_movements_from_trace_calls([call])
    assert len(movements) == 1
    m = movements[0]
    assert m.source_priority == "trace"
    assert call.raw_trace_call_id in m.evidence_ids


def test_unify_movements_merges_log_and_trace() -> None:
    """Same (tx, from, to, amount) observed via both → one canonical record."""
    ev = _link_transfer_event(amount=100)
    log_movements = build_movements_from_transfer_logs([ev])
    trace_movements = build_movements_from_trace_calls(
        [_trace_token_call(amount=100, trace_address=[0])]
    )
    unified = unify_movements(log_movements, trace_movements)
    assert len(unified) == 1
    m = unified[0]
    assert m.source_priority == "log"  # logs win on conflict
    # both evidence ids present
    log_ev_id = log_movements[0].evidence_ids[0]
    trace_ev_id = trace_movements[0].evidence_ids[0]
    assert log_ev_id in m.evidence_ids
    assert trace_ev_id in m.evidence_ids


def test_unify_movements_keeps_trace_only_canonical() -> None:
    """Movement seen only in trace → canonical, source_priority='trace'."""
    trace_movements = build_movements_from_trace_calls([_trace_token_call()])
    unified = unify_movements([], trace_movements)
    assert len(unified) == 1
    assert unified[0].source_priority == "trace"


def test_unify_movements_handles_duplicate_amounts_in_one_tx() -> None:
    """Two distinct (from, to, amount) movements with the same amount in one
    tx must NOT be deduped — they're separate movements."""
    ev1 = _link_transfer_event(amount=100, log_index=0)
    ev2 = _link_transfer_event(amount=100, log_index=1)
    movements = build_movements_from_transfer_logs([ev1, ev2])
    assert len(movements) == 2
    assert movements[0].movement_id != movements[1].movement_id


# --- compute_movement_id ---


def test_compute_movement_id_distinct_for_distinct_movements() -> None:
    a = compute_movement_id(1, "0x1", "0xa", "0xb", 100, 0)
    b = compute_movement_id(1, "0x1", "0xa", "0xb", 100, 1)  # different occurrence
    assert a != b


def test_compute_movement_id_stable_across_runs() -> None:
    """Same inputs → same id (no random state)."""
    args = (1, "0xabc", "0x" + "1" * 40, "0x" + "2" * 40, 9999, 7)
    assert compute_movement_id(*args) == compute_movement_id(*args)


@pytest.mark.parametrize(
    "occurrence",
    [0, 1, 2, 100, 999_999],
)
def test_compute_movement_id_returns_64_char_hex(occurrence: int) -> None:
    mid = compute_movement_id(1, "0xabc", "0x1", "0x2", 100, occurrence)
    assert len(mid) == 64
    int(mid, 16)


def test_compute_movement_id_pure_sha256() -> None:
    """The id must be hashlib.sha256 of the canonical key."""
    canonical = "movement|1|0xabc|0x1|0x2|100|0"
    expected = hashlib.sha256(canonical.encode()).hexdigest()
    assert compute_movement_id(1, "0xabc", "0x1", "0x2", 100, 0) == expected
