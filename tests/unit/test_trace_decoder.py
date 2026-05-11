"""Tests for `decoder.trace_decoder`."""

from __future__ import annotations

import hashlib

from decoder.calldata_decoder import ERC20_TRANSFER_SELECTOR
from decoder.trace_decoder import (
    compute_raw_trace_call_id,
    extract_erc20_transfer_calls,
    walk_trace,
)
from decoder.types import DecodedCall, RawTrace, Receipt

LINK = "0x514910771af9ca656af840dff83e8264ecf986ca"
TX = "0x" + "a" * 64


def _decoded(
    trace_address: list[int],
    success: bool = True,
    parent_success: bool = True,
    contract: str = LINK,
) -> DecodedCall:
    return DecodedCall(
        raw_trace_call_id=compute_raw_trace_call_id(TX, trace_address),
        chain_id=1,
        block_number=18_000_000,
        tx_hash=TX,
        trace_address=trace_address,
        contract_address=contract,
        method_name="transfer",
        method_selector=ERC20_TRANSFER_SELECTOR,
        params={"to": "0x" + "22" * 20, "amount": 100, "from": "0x" + "11" * 20},
        success=success,
        parent_success=parent_success,
    )


def _receipt(status: int = 1) -> Receipt:
    return Receipt(
        chain_id=1,
        block_number=18_000_000,
        block_hash="0x" + "1" * 64,
        tx_hash=TX,
        tx_index=0,
        status=status,
        gas_used=21000,
        effective_gas_price=None,
        cumulative_gas_used=21000,
        contract_address=None,
        logs_count=1,
    )


def test_compute_raw_trace_call_id_deterministic() -> None:
    """Same (tx_hash, trace_address) → same id."""
    a = compute_raw_trace_call_id(TX, [0, 1, 2])
    b = compute_raw_trace_call_id(TX, [0, 1, 2])
    assert a == b
    assert len(a) == 64


def test_compute_raw_trace_call_id_distinct_for_siblings() -> None:
    a = compute_raw_trace_call_id(TX, [0, 1])
    b = compute_raw_trace_call_id(TX, [0, 2])
    assert a != b


def test_compute_raw_trace_call_id_root_distinct_from_first_child() -> None:
    """[] and [0] must not collide."""
    assert compute_raw_trace_call_id(TX, []) != compute_raw_trace_call_id(TX, [0])


def test_compute_raw_trace_call_id_pure_sha256() -> None:
    canonical = f"raw_trace_call|{TX}|0,1,2"
    expected = hashlib.sha256(canonical.encode()).hexdigest()
    assert compute_raw_trace_call_id(TX, [0, 1, 2]) == expected


def test_walk_trace_predicate_filtering() -> None:
    """Predicate filter returns only matching nodes; trace_address populated."""
    inner = RawTrace(
        chain_id=1,
        block_number=1,
        tx_hash=TX,
        type="CALL",
        from_addr="0xabc",
        to_addr=LINK,
        value=0,
        gas=0,
        gas_used=0,
        input_data="0x",
        output="0x",
        error=None,
        revert_reason=None,
        calls=[],
        trace_address=[0, 0],
    )
    middle = RawTrace(
        chain_id=1,
        block_number=1,
        tx_hash=TX,
        type="CALL",
        from_addr="0xroot",
        to_addr="0xother",
        value=0,
        gas=0,
        gas_used=0,
        input_data="0x",
        output="0x",
        error=None,
        revert_reason=None,
        calls=[inner],
        trace_address=[0],
    )
    root = RawTrace(
        chain_id=1,
        block_number=1,
        tx_hash=TX,
        type="CALL",
        from_addr="0xroot",
        to_addr="0xroot_target",
        value=0,
        gas=0,
        gas_used=0,
        input_data="0x",
        output="0x",
        error=None,
        revert_reason=None,
        calls=[middle],
        trace_address=[],
    )

    matches = walk_trace(root, lambda n: n.to_addr == LINK)
    assert len(matches) == 1
    assert matches[0].trace_address == [0, 0]


def test_extract_erc20_transfer_calls_happy_path() -> None:
    call = _decoded([0])
    out = extract_erc20_transfer_calls([call], LINK, {TX: _receipt(1)})
    assert len(out) == 1
    assert out[0].token_address == LINK
    assert out[0].amount == 100


def test_extract_erc20_transfer_calls_filters_reverted() -> None:
    call = _decoded([0], success=False)
    out = extract_erc20_transfer_calls([call], LINK, {TX: _receipt(1)})
    assert out == []


def test_extract_erc20_transfer_calls_filters_failed_parent() -> None:
    call = _decoded([0, 0], parent_success=False)
    out = extract_erc20_transfer_calls([call], LINK, {TX: _receipt(1)})
    assert out == []


def test_extract_erc20_transfer_calls_filters_failed_tx() -> None:
    call = _decoded([0])
    out = extract_erc20_transfer_calls([call], LINK, {TX: _receipt(0)})
    assert out == []


def test_extract_erc20_transfer_calls_includes_only_token_address() -> None:
    """Calls to other ERC-20s are excluded."""
    other_token = "0x" + "f" * 40
    call = _decoded([0], contract=other_token)
    out = extract_erc20_transfer_calls([call], LINK, {TX: _receipt(1)})
    assert out == []


def test_trace_decoder_matches_real_transfer_calldata() -> None:
    """feed real transfer() calldata into the trace
    decoder and assert the path that uses ERC20_TRANSFER_SELECTOR matches.

    The selector `0xa9059cbb` is `keccak256("transfer(address,uint256)")[:4]`,
    encoded as a constant in `decoder.calldata_decoder`. This test confirms
    `decoder.trace_decoder.extract_erc20_transfer_calls` recognises a call
    whose `method_selector` is exactly that constant (i.e. the executable
    selector path, not a comment).
    """
    from decoder.calldata_decoder import (
        ERC20_TRANSFER_FROM_SELECTOR,
        ERC20_TRANSFER_SELECTOR,
        decode_erc20_transfer_calldata,
    )

    # Sanity: the imported constants are the real EVM 4-byte selectors.
    assert ERC20_TRANSFER_SELECTOR == "0xa9059cbb"
    assert ERC20_TRANSFER_FROM_SELECTOR == "0x23b872dd"

    # Real `transfer(0x2222...22, 100 LINK)` calldata: selector + abi-encoded args.
    recipient = "0x" + "22" * 20
    amount = 100 * 10**18
    calldata = ERC20_TRANSFER_SELECTOR + recipient[2:].rjust(64, "0") + format(amount, "064x")

    parsed = decode_erc20_transfer_calldata(calldata)
    assert parsed is not None
    assert parsed["method"] == "transfer"
    assert parsed["to"].lower() == recipient.lower()
    assert parsed["amount"] == amount

    # Now construct a DecodedCall whose method_selector is the imported constant
    # and confirm the trace decoder's executable conditional matches it.
    call = DecodedCall(
        raw_trace_call_id=compute_raw_trace_call_id(TX, [0]),
        chain_id=1,
        block_number=18_000_000,
        tx_hash=TX,
        trace_address=[0],
        contract_address=LINK,
        method_name="transfer",
        method_selector=ERC20_TRANSFER_SELECTOR,
        params={"to": recipient.lower(), "amount": amount, "from": "0x" + "11" * 20},
        success=True,
        parent_success=True,
    )
    out = extract_erc20_transfer_calls([call], LINK, {TX: _receipt(1)})
    assert len(out) == 1, "transfer() selector path must match in trace decoder"
    assert out[0].amount == amount


def test_trace_decoder_matches_real_transferfrom_calldata() -> None:
    """feed real transferFrom() calldata in.

    Selector `0x23b872dd` is `keccak256("transferFrom(address,address,uint256)")[:4]`.
    """
    from decoder.calldata_decoder import (
        ERC20_TRANSFER_FROM_SELECTOR,
        decode_erc20_transfer_calldata,
    )

    assert ERC20_TRANSFER_FROM_SELECTOR == "0x23b872dd"

    sender = "0x" + "11" * 20
    recipient = "0x" + "22" * 20
    amount = 250 * 10**18
    calldata = (
        ERC20_TRANSFER_FROM_SELECTOR
        + sender[2:].rjust(64, "0")
        + recipient[2:].rjust(64, "0")
        + format(amount, "064x")
    )

    parsed = decode_erc20_transfer_calldata(calldata)
    assert parsed is not None
    assert parsed["method"] == "transferFrom"
    assert parsed["from"].lower() == sender.lower()
    assert parsed["to"].lower() == recipient.lower()
    assert parsed["amount"] == amount

    call = DecodedCall(
        raw_trace_call_id=compute_raw_trace_call_id(TX, [0]),
        chain_id=1,
        block_number=18_000_000,
        tx_hash=TX,
        trace_address=[0],
        contract_address=LINK,
        method_name="transferFrom",
        method_selector=ERC20_TRANSFER_FROM_SELECTOR,
        params={"from": sender.lower(), "to": recipient.lower(), "amount": amount},
        success=True,
        parent_success=True,
    )
    out = extract_erc20_transfer_calls([call], LINK, {TX: _receipt(1)})
    assert len(out) == 1, "transferFrom() selector path must match in trace decoder"
    assert out[0].amount == amount
    assert out[0].method_name == "transferFrom"
