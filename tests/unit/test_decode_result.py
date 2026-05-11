"""Tests for `decoder.types.DecodeResult` failure-reason coverage."""

from __future__ import annotations

from typing import get_args

from decoder.types import DecodedEvent, DecodeFailureReason, DecodeResult


def _decoded() -> DecodedEvent:
    return DecodedEvent(
        raw_log_id="rl",
        decoded_event_id="de",
        chain_id=1,
        block_number=1,
        tx_hash="0xtx",
        log_index=0,
        contract_address="0xabc",
        event_name="Transfer",
        event_signature="0xsig",
        indexed_params={},
        data_params={},
    )


def test_decode_result_success_carries_decoded() -> None:
    res = DecodeResult(
        raw_id="rid",
        success=True,
        decoded=_decoded(),
        failure_reason=None,
        failure_detail=None,
    )
    assert res.success
    assert res.decoded is not None
    assert res.failure_reason is None


def test_decode_result_failure_carries_reason() -> None:
    res = DecodeResult(
        raw_id="rid",
        success=False,
        decoded=None,
        failure_reason="unknown_topic",
        failure_detail="topic0=0xff",
    )
    assert not res.success
    assert res.decoded is None
    assert res.failure_reason == "unknown_topic"


def test_decode_result_all_failure_reasons_are_literal() -> None:
    """Exhaustiveness: every literal value in DecodeFailureReason can be set."""
    expected = {
        "unknown_topic",
        "abi_mismatch",
        "malformed_data",
        "unregistered_contract",
        "phase_not_found",
    }
    actual = set(get_args(DecodeFailureReason))
    assert expected == actual

    for reason in actual:
        res = DecodeResult(
            raw_id="rid",
            success=False,
            decoded=None,
            failure_reason=reason,  # type: ignore[arg-type]
            failure_detail=None,
        )
        assert res.failure_reason == reason
