"""Tests for `decoder.calldata_decoder`.

Covers extract_method_selector, decode_calldata, and the ERC-20 fast path.
"""

from __future__ import annotations

import pytest

from decoder.calldata_decoder import (
    ERC20_TRANSFER_FROM_SELECTOR,
    ERC20_TRANSFER_SELECTOR,
    decode_calldata,
    decode_erc20_transfer_calldata,
    extract_method_selector,
)
from decoder.types import Abi


def test_extract_method_selector_basic() -> None:
    sel = extract_method_selector("0xa9059cbb000000000000000000000000aabb")
    assert sel == "0xa9059cbb"


def test_extract_method_selector_empty() -> None:
    assert extract_method_selector("0x") == "0x"
    assert extract_method_selector("") == "0x"


def test_extract_method_selector_short_calldata() -> None:
    # less than 4 bytes — not a real call
    assert extract_method_selector("0xab") == "0x"


def test_decode_erc20_transfer_decodes_to_method_to_amount() -> None:
    """Pure-fast-path ERC-20 transfer decoding."""
    to = "0x" + "bb" * 20
    amount = 12345
    body = to[2:].rjust(64, "0") + format(amount, "064x")
    calldata = ERC20_TRANSFER_SELECTOR + body
    out = decode_erc20_transfer_calldata(calldata)
    assert out is not None
    assert out["method"] == "transfer"
    assert out["from"] is None
    assert out["to"] == to
    assert out["amount"] == amount


def test_decode_erc20_transferFrom_decodes_from_to_amount() -> None:  # noqa: N802
    from_addr = "0x" + "aa" * 20
    to = "0x" + "bb" * 20
    amount = 67890
    body = from_addr[2:].rjust(64, "0") + to[2:].rjust(64, "0") + format(amount, "064x")
    calldata = ERC20_TRANSFER_FROM_SELECTOR + body
    out = decode_erc20_transfer_calldata(calldata)
    assert out is not None
    assert out["method"] == "transferFrom"
    assert out["from"] == from_addr
    assert out["to"] == to
    assert out["amount"] == amount


def test_decode_erc20_transfer_unknown_selector_returns_none() -> None:
    out = decode_erc20_transfer_calldata("0xdeadbeef0000")
    assert out is None


def test_decode_calldata_unknown_selector() -> None:
    abi = Abi(
        abi_version="v1",
        json_abi=[
            {
                "type": "function",
                "name": "stake",
                "inputs": [{"name": "amount", "type": "uint256"}],
                "outputs": [],
            }
        ],
    )
    result = decode_calldata("0xdeadbeef" + "00" * 32, abi)
    assert result.success is False
    assert result.failure_reason == "unknown_topic"


def test_decode_calldata_success() -> None:
    abi = Abi(
        abi_version="v1",
        json_abi=[
            {
                "type": "function",
                "name": "stake",
                "inputs": [{"name": "amount", "type": "uint256"}],
                "outputs": [],
            }
        ],
    )
    from eth_utils import keccak

    selector = "0x" + keccak(text="stake(uint256)").hex()[:8]
    body = format(123, "064x")
    result = decode_calldata(selector + body, abi)
    assert result.success is True
    assert result.decoded is not None
    assert result.decoded.method_name == "stake"
    assert result.decoded.params["amount"] == 123


def test_decode_calldata_malformed_data() -> None:
    abi = Abi(
        abi_version="v1",
        json_abi=[
            {
                "type": "function",
                "name": "stake",
                "inputs": [{"name": "amount", "type": "uint256"}],
                "outputs": [],
            }
        ],
    )
    from eth_utils import keccak

    selector = "0x" + keccak(text="stake(uint256)").hex()[:8]
    # 1-byte body: not a multiple of 32
    result = decode_calldata(selector + "ab", abi)
    assert result.success is False
    assert result.failure_reason == "malformed_data"


@pytest.mark.parametrize(
    "calldata,expected",
    [
        ("0xabcd1234ff", "0xabcd1234"),
        ("0X12345678", "0x12345678"),
        ("12345678", "0x12345678"),
    ],
)
def test_extract_method_selector_normalizes(calldata: str, expected: str) -> None:
    assert extract_method_selector(calldata) == expected
