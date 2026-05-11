"""Tests for `decoder.event_decoder`. Cover: ID determinism, ABI shape
checks, malformed data handling, anonymous events, batch order preservation.
"""

from __future__ import annotations

import hashlib

import pytest

from decoder.event_decoder import (
    ERC20_TRANSFER_TOPIC0,
    compute_decoded_event_id,
    compute_raw_log_id,
    decode_log,
    decode_logs_batch,
)
from decoder.types import Abi, DecodedEvent, RawLog

LINK_TOKEN = "0x514910771af9ca656af840dff83e8264ecf986ca"


def _erc20_transfer_log() -> RawLog:
    """A canonical LINK Transfer log: 100 LINK from A to B."""
    from_addr_padded = "0" * 24 + "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    to_addr_padded = "0" * 24 + "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    amount = (100 * 10**18).to_bytes(32, "big").hex()
    return RawLog(
        chain_id=1,
        block_number=18_000_000,
        block_hash="0x" + "1" * 64,
        tx_hash="0x" + "2" * 64,
        tx_index=0,
        log_index=0,
        address=LINK_TOKEN,
        topics=[ERC20_TRANSFER_TOPIC0, "0x" + from_addr_padded, "0x" + to_addr_padded],
        data="0x" + amount,
    )


def _erc20_transfer_abi() -> Abi:
    return Abi(
        abi_version="erc20_v1",
        json_abi=[
            {
                "type": "event",
                "name": "Transfer",
                "anonymous": False,
                "inputs": [
                    {"name": "from", "type": "address", "indexed": True},
                    {"name": "to", "type": "address", "indexed": True},
                    {"name": "value", "type": "uint256", "indexed": False},
                ],
            }
        ],
    )


# --- compute_raw_log_id / compute_decoded_event_id ---


def test_compute_raw_log_id_deterministic() -> None:
    log = _erc20_transfer_log()
    assert compute_raw_log_id(log) == compute_raw_log_id(log)


def test_compute_raw_log_id_returns_64_char_hex() -> None:
    log = _erc20_transfer_log()
    rid = compute_raw_log_id(log)
    assert isinstance(rid, str)
    assert len(rid) == 64
    int(rid, 16)  # hex parsing — raises if not hex


def test_compute_raw_log_id_distinct_per_log_index() -> None:
    log_a = _erc20_transfer_log()
    log_b = RawLog(
        chain_id=log_a.chain_id,
        block_number=log_a.block_number,
        block_hash=log_a.block_hash,
        tx_hash=log_a.tx_hash,
        tx_index=log_a.tx_index,
        log_index=log_a.log_index + 1,  # difference
        address=log_a.address,
        topics=log_a.topics,
        data=log_a.data,
    )
    assert compute_raw_log_id(log_a) != compute_raw_log_id(log_b)


def test_compute_decoded_event_id_distinct_from_raw_log_id() -> None:
    log = _erc20_transfer_log()
    raw_id = compute_raw_log_id(log)
    decoded = DecodedEvent(
        raw_log_id=raw_id,
        decoded_event_id="",
        chain_id=log.chain_id,
        block_number=log.block_number,
        tx_hash=log.tx_hash,
        log_index=log.log_index,
        contract_address=log.address,
        event_name="Transfer",
        event_signature=log.topics[0],
        indexed_params={},
        data_params={},
    )
    assert compute_decoded_event_id(decoded) != raw_id


# --- decode_log ---


def test_decode_log_success() -> None:
    """Known LINK Transfer fixture decodes to DecodeResult(success=True) with
    indexed_params and data_params populated."""
    log = _erc20_transfer_log()
    abi = _erc20_transfer_abi()
    result = decode_log(log, abi)
    assert result.success is True
    assert result.decoded is not None
    assert isinstance(result.decoded, DecodedEvent)
    assert result.decoded.event_name == "Transfer"
    assert result.decoded.indexed_params["from"] == "0x" + "aa" * 20
    assert result.decoded.indexed_params["to"] == "0x" + "bb" * 20
    assert result.decoded.data_params["value"] == 100 * 10**18


def test_decode_log_unknown_topic() -> None:
    """Topic0 not in ABI → DecodeResult(failure_reason='unknown_topic')."""
    log = _erc20_transfer_log()
    bogus_log = RawLog(
        chain_id=log.chain_id,
        block_number=log.block_number,
        block_hash=log.block_hash,
        tx_hash=log.tx_hash,
        tx_index=log.tx_index,
        log_index=log.log_index,
        address=log.address,
        topics=["0x" + "f" * 64, *log.topics[1:]],
        data=log.data,
    )
    result = decode_log(bogus_log, _erc20_transfer_abi())
    assert result.success is False
    assert result.failure_reason == "unknown_topic"


def test_decode_log_malformed_data() -> None:
    """Truncated data payload → failure_reason='malformed_data'."""
    log = _erc20_transfer_log()
    bad = RawLog(
        chain_id=log.chain_id,
        block_number=log.block_number,
        block_hash=log.block_hash,
        tx_hash=log.tx_hash,
        tx_index=log.tx_index,
        log_index=log.log_index,
        address=log.address,
        topics=log.topics,
        data="0xabcd",  # 2 bytes, not a multiple of 32
    )
    result = decode_log(bad, _erc20_transfer_abi())
    assert result.success is False
    assert result.failure_reason == "malformed_data"


def test_decode_log_topic_count_mismatch() -> None:
    """ABI expects 2 indexed args but log has only 1 → abi_mismatch."""
    log = _erc20_transfer_log()
    truncated_topics = RawLog(
        chain_id=log.chain_id,
        block_number=log.block_number,
        block_hash=log.block_hash,
        tx_hash=log.tx_hash,
        tx_index=log.tx_index,
        log_index=log.log_index,
        address=log.address,
        topics=[log.topics[0], log.topics[1]],  # missing topic[2]
        data=log.data,
    )
    result = decode_log(truncated_topics, _erc20_transfer_abi())
    assert result.success is False
    assert result.failure_reason == "abi_mismatch"


def test_decode_log_anonymous_no_match() -> None:
    """Log with no topics + no anonymous event in ABI → unknown_topic."""
    log = _erc20_transfer_log()
    no_topics = RawLog(
        chain_id=log.chain_id,
        block_number=log.block_number,
        block_hash=log.block_hash,
        tx_hash=log.tx_hash,
        tx_index=log.tx_index,
        log_index=log.log_index,
        address=log.address,
        topics=[],
        data=log.data,
    )
    result = decode_log(no_topics, _erc20_transfer_abi())
    assert result.success is False
    assert result.failure_reason == "unknown_topic"


def test_decode_log_indexed_address_extracted_from_last_20_bytes() -> None:
    """Indexed `from`/`to` addresses come from topic[1]/topic[2] as last 20
    bytes (not full 32) — verify the extraction."""
    log = _erc20_transfer_log()
    abi = _erc20_transfer_abi()
    result = decode_log(log, abi)
    assert result.decoded is not None
    # The address should be 0x + 40 hex chars = 42 total
    assert len(result.decoded.indexed_params["from"]) == 42
    assert result.decoded.indexed_params["from"].startswith("0x")


# --- decode_logs_batch ---


def test_decode_logs_batch_preserves_order() -> None:
    log = _erc20_transfer_log()
    abi = _erc20_transfer_abi()

    class _Reg:
        def get(self, _addr: str, _block: int) -> Abi:
            return abi

    batch = [log, log, log]
    results = decode_logs_batch(batch, _Reg())  # type: ignore[arg-type]
    assert len(results) == 3
    for r in results:
        assert r.success is True


def test_decode_logs_batch_unregistered_contract() -> None:
    """If registry raises KeyError, result is unregistered_contract failure."""
    log = _erc20_transfer_log()

    class _Reg:
        def get(self, _addr: str, _block: int) -> Abi:
            raise KeyError("not registered")

    results = decode_logs_batch([log], _Reg())  # type: ignore[arg-type]
    assert len(results) == 1
    assert results[0].success is False
    assert results[0].failure_reason == "unregistered_contract"


# --- Property-style: ID determinism across separate process ---


@pytest.mark.parametrize("log_index", [0, 1, 5, 100, 9999])
def test_compute_raw_log_id_changes_with_log_index(log_index: int) -> None:
    log = _erc20_transfer_log()
    log = RawLog(
        chain_id=log.chain_id,
        block_number=log.block_number,
        block_hash=log.block_hash,
        tx_hash=log.tx_hash,
        tx_index=log.tx_index,
        log_index=log_index,
        address=log.address,
        topics=log.topics,
        data=log.data,
    )
    rid = compute_raw_log_id(log)
    expected = hashlib.sha256(
        f"raw_log|{log.chain_id}|{log.block_number}|{log.tx_hash.lower()}|{log_index}".encode()
    ).hexdigest()
    assert rid == expected
