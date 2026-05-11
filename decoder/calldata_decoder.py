"""Calldata decoding for entry-point methods on protocol contracts.

Used to enrich `EconomicAction` records with caller intent — the event alone may
not distinguish e.g. "stake" from "stakeOnBehalfOf". For Payment Abstraction the
calldata also carries the swap tuple that the trace tree exposes.

Decoding is via `eth_abi` against the function inputs in the ABI.

ERC-20 selectors used elsewhere in the pipeline:
    transfer(address,uint256)              0xa9059cbb
    transferFrom(address,address,uint256)  0x23b872dd
"""

from __future__ import annotations

from typing import Any

from eth_abi import decode as abi_decode

from decoder.abi_registry import AbiRegistry
from decoder.types import Abi, DecodedCall, DecodeResult

# Common ERC-20 method selectors (used by trace_decoder; re-exported here)
ERC20_TRANSFER_SELECTOR = "0xa9059cbb"
ERC20_TRANSFER_FROM_SELECTOR = "0x23b872dd"


def extract_method_selector(calldata: str) -> str:
    """First 4 bytes (8 hex chars + 0x prefix) of `calldata`. Empty calldata → '0x'.

    The selector is keccak256("methodName(types...)")[:4].

    Edge case: calldata that is not 0x-prefixed is accepted (we strip a leading
    0x if present, otherwise treat the whole string as hex). Empty / "0x" / "0x0"
    return "0x".
    """
    if not calldata or calldata in ("0x", "0X"):
        return "0x"
    raw = calldata[2:] if calldata.startswith(("0x", "0X")) else calldata
    if len(raw) < 8:
        return "0x"
    return "0x" + raw[:8].lower()


def decode_calldata(calldata: str, abi: Abi) -> DecodeResult:
    """Returns DecodeResult containing a DecodedCall on success.

    `DecodedCall.trace_address` is `[]` for top-level tx calldata. For the trace
    decoder, that field is filled in by `trace_decoder.decode_trace_calls`.

    Failure reasons:
      - "unknown_topic": selector not present in ABI (we reuse the same enum
        value for symmetry with event_decoder; the failure_detail clarifies)
      - "abi_mismatch": types don't decode cleanly
      - "malformed_data": calldata is not a multiple of 32 bytes after the
        4-byte selector
    """
    selector = extract_method_selector(calldata)
    method = _find_method_by_selector(abi, selector)
    if method is None:
        return DecodeResult(
            raw_id="",
            success=False,
            decoded=None,
            failure_reason="unknown_topic",
            failure_detail=f"selector {selector} not in ABI",
        )

    raw = calldata[2:] if calldata.startswith(("0x", "0X")) else calldata
    body_hex = raw[8:]
    body = bytes.fromhex(body_hex) if body_hex else b""

    if body and len(body) % 32 != 0:
        return DecodeResult(
            raw_id="",
            success=False,
            decoded=None,
            failure_reason="malformed_data",
            failure_detail=f"calldata body length {len(body)} not multiple of 32",
        )

    inputs = method.get("inputs", [])
    try:
        decoded_values = abi_decode([inp["type"] for inp in inputs], body) if inputs else ()
    except Exception as exc:  # noqa: BLE001
        return DecodeResult(
            raw_id="",
            success=False,
            decoded=None,
            failure_reason="abi_mismatch",
            failure_detail=f"calldata decode failed: {exc}",
        )

    params: dict[str, Any] = {}
    for inp, val in zip(inputs, decoded_values, strict=True):
        if inp["type"] == "address" and isinstance(val, str):
            params[inp["name"]] = val.lower()
        elif isinstance(val, bytes):
            params[inp["name"]] = "0x" + val.hex()
        else:
            params[inp["name"]] = val

    decoded_call = DecodedCall(
        raw_trace_call_id="",  # populated by trace_decoder when it has a tx context
        chain_id=0,
        block_number=0,
        tx_hash="",
        trace_address=[],
        contract_address=None,
        method_name=method.get("name", "<unnamed>"),
        method_selector=selector,
        params=params,
        success=True,
        parent_success=True,
    )
    return DecodeResult(
        raw_id="",
        success=True,
        decoded=decoded_call,
        failure_reason=None,
        failure_detail=None,
    )


def _find_method_by_selector(abi: Abi, selector: str) -> dict[str, Any] | None:
    """Locate the function entry in `abi` whose computed 4-byte selector matches.

    Returns the JSON ABI dict, or None if no match.
    """
    target = selector.lower()
    for entry in abi.json_abi:
        if entry.get("type") != "function":
            continue
        try:
            entry_selector = AbiRegistry.method_selector(abi, entry["name"])
        except KeyError:
            continue
        if entry_selector.lower() == target:
            return entry
    return None


def decode_erc20_transfer_calldata(calldata: str) -> dict[str, Any] | None:
    """Specialized fast-path: decode `transfer(address,uint256)` / `transferFrom(
    address,address,uint256)` calldata WITHOUT needing an ABI.

    Returns:
        {"method": "transfer"|"transferFrom", "from": str|None, "to": str, "amount": int}

    None if the selector is not a known ERC-20 transfer selector. Used by the
    trace decoder's hot loop where consulting the registry per call would be
    wasteful.

    `from` is None for `transfer` (the caller is the implicit `from`); the
    trace decoder fills it in from the trace frame's `from_address`.
    """
    selector = extract_method_selector(calldata)
    raw = calldata[2:] if calldata.startswith(("0x", "0X")) else calldata
    body = bytes.fromhex(raw[8:]) if len(raw) >= 8 else b""

    if selector == ERC20_TRANSFER_SELECTOR:
        if len(body) < 64:
            return None
        try:
            to_addr, amount = abi_decode(["address", "uint256"], body[:64])
        except Exception:  # noqa: BLE001
            return None
        return {
            "method": "transfer",
            "from": None,
            "to": to_addr.lower(),
            "amount": int(amount),
        }
    if selector == ERC20_TRANSFER_FROM_SELECTOR:
        if len(body) < 96:
            return None
        try:
            from_addr, to_addr, amount = abi_decode(["address", "address", "uint256"], body[:96])
        except Exception:  # noqa: BLE001
            return None
        return {
            "method": "transferFrom",
            "from": from_addr.lower(),
            "to": to_addr.lower(),
            "amount": int(amount),
        }
    return None


# Re-export _hex_to_bytes so callers (e.g. trace_decoder) don't reach into
# event_decoder for it.
__all__ = [
    "ERC20_TRANSFER_FROM_SELECTOR",
    "ERC20_TRANSFER_SELECTOR",
    "decode_calldata",
    "decode_erc20_transfer_calldata",
    "extract_method_selector",
]
