"""Event log decoding.

Returns DecodeResult — successes carry a DecodedEvent; failures carry a structured
reason. Failures are persisted to `decode_failures` parquet so the dbt
`int_decode_failures` model and the unknown-signature monitor can surface them.

ID functions are public surface — these are the idempotency contract.

Decoding happens via `eth_abi.decode`, not via `web3.py` contract methods. We work
at the bytes level so the wire layout is observable and reviewable.

ERC-20 Transfer reference (the canonical event the pipeline relies on):

    event signature:  Transfer(address indexed from, address indexed to, uint256 value)
    topic0:           0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef
    topics[1]:        from address, padded to 32 bytes (last 20 = address)
    topics[2]:        to address, padded
    data:             abi-encoded uint256 value (one 32-byte word)
"""

from __future__ import annotations

import hashlib
from typing import Any

from eth_abi.abi import decode as abi_decode

from decoder.abi_registry import AbiRegistry
from decoder.types import Abi, DecodedEvent, DecodeResult, RawLog

# ERC-20 Transfer event signature (topic0). Hardcoded as a known constant to
# avoid recomputing keccak on hot path.
ERC20_TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def compute_raw_log_id(log: RawLog) -> str:
    """SHA-256 of `(chain_id, block_number, tx_hash, log_index)`. Pure; replay-stable."""
    canonical = f"raw_log|{log.chain_id}|{log.block_number}|{log.tx_hash.lower()}|{log.log_index}"
    return hashlib.sha256(canonical.encode()).hexdigest()


def compute_decoded_event_id(decoded: DecodedEvent) -> str:
    """Same key range as `raw_log_id`, tagged `decoded` to avoid raw/decoded join collisions."""
    canonical = (
        f"decoded_event|{decoded.chain_id}|{decoded.block_number}"
        f"|{decoded.tx_hash.lower()}|{decoded.log_index}"
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _topic_to_address(topic_hex: str) -> str:
    """Extract the 20-byte address from a 32-byte topic.

    Indexed `address` parameters are right-aligned in a 32-byte topic — bytes
    [12:32] hold the address, bytes [0:12] are zero padding.

    Example:
        topic   = 0x000000000000000000000000aabbccddeeff00112233445566778899aabbccdd
        address = 0xaabbccddeeff00112233445566778899aabbccdd
    """
    if not topic_hex.startswith("0x"):
        topic_hex = "0x" + topic_hex
    if len(topic_hex) != 66:
        raise ValueError(f"topic must be 32 bytes (66 hex chars w/ 0x), got {len(topic_hex)}")
    return "0x" + topic_hex[-40:].lower()


def _hex_to_bytes(hex_str: str) -> bytes:
    """Strip 0x and convert to bytes. Empty string → empty bytes."""
    s = hex_str[2:] if hex_str.startswith("0x") else hex_str
    if not s:
        return b""
    if len(s) % 2 != 0:
        raise ValueError(f"odd-length hex string: {hex_str!r}")
    return bytes.fromhex(s)


def _find_event_abi(abi: Abi, topic0: str) -> dict[str, Any] | None:
    """Locate the event entry in the ABI whose computed topic0 matches.

    Returns the JSON ABI dict for the event, or None if no match.
    """
    target = topic0.lower()
    if not target.startswith("0x"):
        target = "0x" + target
    for entry in abi.json_abi:
        if entry.get("type") != "event":
            continue
        if entry.get("anonymous"):
            # Anonymous events don't carry topic0 — the spec says to handle them
            # distinctly, see decode_log.
            continue
        try:
            sig = AbiRegistry.event_signature(abi, entry["name"])
        except (KeyError, ValueError):
            continue
        if sig.lower() == target:
            return entry
    return None


def decode_log(log: RawLog, abi: Abi) -> DecodeResult:
    """Decode a single log against the given ABI. Returns DecodeResult with either
    `decoded` populated or `failure_reason` set.

    Failure reasons:
      - "unknown_topic": topic0 not in ABI's events
      - "abi_mismatch": types don't decode cleanly OR topic count doesn't
        match the ABI's expected indexed-arg count
      - "malformed_data": data payload length invalid

    Gotcha: a log without topic0 is "anonymous" — handled distinctly. We treat
    a topic-less log without a matching anonymous entry as `unknown_topic`.

    Edge case: if topic count doesn't match the ABI's indexed-arg count, returns
    `abi_mismatch` (this catches events where the ABI shape evolved).
    """
    raw_id = compute_raw_log_id(log)

    # Anonymous-event handling: no topic0 to match by
    if not log.topics:
        # Try to find any anonymous event in the ABI; if none, fail.
        anon = next(
            (e for e in abi.json_abi if e.get("type") == "event" and e.get("anonymous")),
            None,
        )
        if anon is None:
            return DecodeResult(
                raw_id=raw_id,
                success=False,
                decoded=None,
                failure_reason="unknown_topic",
                failure_detail="anonymous log; no anonymous event in ABI",
            )
        event_entry = anon
        topic_consumed = 0  # anonymous events use ALL topics for indexed args
    else:
        topic0 = log.topics[0]
        found_event_entry = _find_event_abi(abi, topic0)
        if found_event_entry is None:
            return DecodeResult(
                raw_id=raw_id,
                success=False,
                decoded=None,
                failure_reason="unknown_topic",
                failure_detail=f"topic0={topic0} not in ABI",
            )
        event_entry = found_event_entry
        topic_consumed = 1  # topic[0] is the signature

    inputs: list[dict[str, Any]] = list(event_entry.get("inputs", []))
    indexed_inputs = [i for i in inputs if i.get("indexed")]
    non_indexed_inputs = [i for i in inputs if not i.get("indexed")]

    # The number of indexed inputs must equal len(topics) - topic_consumed.
    expected_indexed_topics = len(log.topics) - topic_consumed
    if len(indexed_inputs) != expected_indexed_topics:
        return DecodeResult(
            raw_id=raw_id,
            success=False,
            decoded=None,
            failure_reason="abi_mismatch",
            failure_detail=(
                f"event '{event_entry.get('name')}': "
                f"abi has {len(indexed_inputs)} indexed args, log has "
                f"{expected_indexed_topics} non-signature topics"
            ),
        )

    # Decode indexed parameters from topics[1:] (or topics[:] for anonymous)
    indexed_params: dict[str, Any] = {}
    try:
        for i, inp in enumerate(indexed_inputs):
            topic = log.topics[topic_consumed + i]
            if inp["type"] == "address":
                indexed_params[inp["name"]] = _topic_to_address(topic)
            else:
                # uint/int/bytes32 etc — decode the 32-byte topic with eth_abi
                indexed_params[inp["name"]] = abi_decode([inp["type"]], _hex_to_bytes(topic))[0]
    except Exception as exc:  # noqa: BLE001
        return DecodeResult(
            raw_id=raw_id,
            success=False,
            decoded=None,
            failure_reason="abi_mismatch",
            failure_detail=f"indexed decode failed: {exc}",
        )

    # Decode non-indexed parameters from data
    data_bytes = _hex_to_bytes(log.data)
    data_params: dict[str, Any] = {}
    if non_indexed_inputs:
        # data should be a multiple of 32 bytes for any well-formed event
        if len(data_bytes) == 0 or len(data_bytes) % 32 != 0:
            return DecodeResult(
                raw_id=raw_id,
                success=False,
                decoded=None,
                failure_reason="malformed_data",
                failure_detail=f"data length {len(data_bytes)} not multiple of 32",
            )
        try:
            decoded_values = abi_decode(
                [inp["type"] for inp in non_indexed_inputs],
                data_bytes,
            )
        except Exception as exc:  # noqa: BLE001
            return DecodeResult(
                raw_id=raw_id,
                success=False,
                decoded=None,
                failure_reason="abi_mismatch",
                failure_detail=f"data decode failed: {exc}",
            )
        for inp, val in zip(non_indexed_inputs, decoded_values, strict=True):
            if inp["type"] == "address":
                data_params[inp["name"]] = val.lower() if isinstance(val, str) else val
            elif isinstance(val, bytes):
                data_params[inp["name"]] = "0x" + val.hex()
            else:
                data_params[inp["name"]] = val

    decoded_event = DecodedEvent(
        raw_log_id=raw_id,
        decoded_event_id="",  # filled after the event is constructed (see below)
        chain_id=log.chain_id,
        block_number=log.block_number,
        tx_hash=log.tx_hash.lower(),
        log_index=log.log_index,
        contract_address=log.address.lower(),
        event_name=event_entry.get("name", "<unnamed>"),
        event_signature=log.topics[0].lower() if log.topics else "",
        indexed_params=indexed_params,
        data_params=data_params,
    )
    # decoded_event_id is a deterministic function of the same canonical key —
    # rebuild a copy with the id populated.
    decoded_with_id = DecodedEvent(
        raw_log_id=decoded_event.raw_log_id,
        decoded_event_id=compute_decoded_event_id(decoded_event),
        chain_id=decoded_event.chain_id,
        block_number=decoded_event.block_number,
        tx_hash=decoded_event.tx_hash,
        log_index=decoded_event.log_index,
        contract_address=decoded_event.contract_address,
        event_name=decoded_event.event_name,
        event_signature=decoded_event.event_signature,
        indexed_params=decoded_event.indexed_params,
        data_params=decoded_event.data_params,
    )
    return DecodeResult(
        raw_id=raw_id,
        success=True,
        decoded=decoded_with_id,
        failure_reason=None,
        failure_detail=None,
    )


def decode_logs_batch(logs: list[RawLog], registry: AbiRegistry) -> list[DecodeResult]:
    """Resolves ABI per `(log.address, log.block_number)` via registry; decodes
    each log. Returns one DecodeResult per input log, in input order.

    If an address is not in the registry → returns `unregistered_contract`.
    """
    out: list[DecodeResult] = []
    for log in logs:
        try:
            abi = registry.get(log.address.lower(), log.block_number)
        except KeyError as exc:
            out.append(
                DecodeResult(
                    raw_id=compute_raw_log_id(log),
                    success=False,
                    decoded=None,
                    failure_reason="unregistered_contract",
                    failure_detail=str(exc),
                )
            )
            continue
        out.append(decode_log(log, abi))
    return out
