"""Ancestor-success behavioural tests (the ancestor-success test + the trace-success invariant).

Builds a real multi-level `RawTrace` tree with grandparent -> parent ->
LINK.transferFrom (depth 3) and exercises the real trace decoder. Asserts:
  - When all ancestors succeed -> the LINK transfer movement IS extracted.
  - When the PARENT (intermediate) call reverted -> the descendant movement is
    REJECTED.
  - When the GRANDPARENT reverted but the parent succeeded -> the descendant
    movement is STILL REJECTED (the case the old `parent.success`-only check
    missed; the trace-success invariant demands every ancestor on the path).
  - When `receipt.status == 0` (top-level revert) -> the movement is REJECTED.

We use the real `decoder.trace_decoder.decode_trace_calls +
extract_erc20_transfer_calls` pipeline (not a synthetic single-object mock).
"""

from __future__ import annotations

from decoder.abi_registry import AbiRegistry
from decoder.calldata_decoder import ERC20_TRANSFER_FROM_SELECTOR, ERC20_TRANSFER_SELECTOR
from decoder.trace_decoder import decode_trace_calls, extract_erc20_transfer_calls
from decoder.types import DecodedCall, RawTrace, Receipt

LINK = "0x514910771af9ca656af840dff83e8264ecf986ca"
TX = "0x" + "a" * 64
GRANDPARENT_ADDR = "0x" + "cc" * 20
PARENT_ADDR = "0x" + "dd" * 20
LINK_AMOUNT = 100 * 10**18
SENDER = "0x" + "11" * 20
RECIPIENT = "0x" + "22" * 20


def _erc20_transferfrom_calldata() -> str:
    """Real ERC-20 transferFrom(0x11..., 0x22..., 100 LINK) calldata.

    Selector `0x23b872dd` followed by three abi-encoded 32-byte words.
    """
    return (
        ERC20_TRANSFER_FROM_SELECTOR
        + SENDER[2:].rjust(64, "0")
        + RECIPIENT[2:].rjust(64, "0")
        + format(LINK_AMOUNT, "064x")
    )


def _link_transfer_node() -> RawTrace:
    """The LINK.transferFrom leaf call at depth 3 (trace_address=[0,0,0])."""
    return RawTrace(
        chain_id=1,
        block_number=18_000_000,
        tx_hash=TX,
        type="CALL",
        from_addr=PARENT_ADDR,
        to_addr=LINK,
        value=0,
        gas=50_000,
        gas_used=20_000,
        input_data=_erc20_transferfrom_calldata(),
        output="0x" + "0" * 63 + "1",
        error=None,
        revert_reason=None,
        calls=[],
        trace_address=[0, 0, 0],
    )


def _build_tree(
    parent_reverted: bool = False,
    grandparent_reverted: bool = False,
    leaf_reverted: bool = False,
) -> RawTrace:
    """Build a real 3-level call tree:

    root            (trace=[],   always success)
      calls[0]      grandparent  (trace=[0],   success = !grandparent_reverted)
        calls[0]    parent       (trace=[0,0], success = !parent_reverted)
          calls[0]  LINK.transferFrom leaf (trace=[0,0,0])
    """
    leaf = _link_transfer_node()
    if leaf_reverted:
        leaf = RawTrace(
            chain_id=leaf.chain_id,
            block_number=leaf.block_number,
            tx_hash=leaf.tx_hash,
            type=leaf.type,
            from_addr=leaf.from_addr,
            to_addr=leaf.to_addr,
            value=leaf.value,
            gas=leaf.gas,
            gas_used=leaf.gas_used,
            input_data=leaf.input_data,
            output=leaf.output,
            error="execution reverted",
            revert_reason="ERC20: insufficient allowance",
            calls=leaf.calls,
            trace_address=leaf.trace_address,
        )

    parent = RawTrace(
        chain_id=1,
        block_number=18_000_000,
        tx_hash=TX,
        type="CALL",
        from_addr=GRANDPARENT_ADDR,
        to_addr=PARENT_ADDR,
        value=0,
        gas=80_000,
        gas_used=30_000,
        input_data="0x",
        output="0x",
        error="execution reverted" if parent_reverted else None,
        revert_reason="parent revert" if parent_reverted else None,
        calls=[leaf],
        trace_address=[0, 0],
    )

    grandparent = RawTrace(
        chain_id=1,
        block_number=18_000_000,
        tx_hash=TX,
        type="CALL",
        from_addr="0x" + "ee" * 20,
        to_addr=GRANDPARENT_ADDR,
        value=0,
        gas=100_000,
        gas_used=40_000,
        input_data="0x",
        output="0x",
        error="execution reverted" if grandparent_reverted else None,
        revert_reason="grandparent revert" if grandparent_reverted else None,
        calls=[parent],
        trace_address=[0],
    )

    return RawTrace(
        chain_id=1,
        block_number=18_000_000,
        tx_hash=TX,
        type="CALL",
        from_addr="0x" + "ff" * 20,
        to_addr="0x" + "ab" * 20,
        value=0,
        gas=150_000,
        gas_used=50_000,
        input_data="0x",
        output="0x",
        error=None,
        revert_reason=None,
        calls=[grandparent],
        trace_address=[],
    )


def _empty_registry() -> AbiRegistry:
    """Empty AbiRegistry; the selector fast-path inside `decode_trace_calls`
    recognises transferFrom by `0x23b872dd` without needing a registered ABI."""
    return AbiRegistry(phases_by_address={})


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
        logs_count=0,
    )


# --- Real tree behavioural tests (H4) --------------------------------------


def test_h4_all_ancestors_success_emits_movement() -> None:
    """Top-level success, every ancestor success, leaf success -> movement IS
    extracted via the real decode pipeline."""
    root = _build_tree()
    decoded = decode_trace_calls(root, _empty_registry())
    movements = extract_erc20_transfer_calls(
        decoded_calls=decoded, token_address=LINK, receipts_by_tx={TX: _receipt(1)}
    )
    assert len(movements) == 1, "expected the LINK transferFrom to be extracted"
    m = movements[0]
    assert m.token_address == LINK
    assert m.amount == LINK_AMOUNT
    assert m.method_name == "transferFrom"


def test_h4_parent_revert_rejects_descendant() -> None:
    """Parent (intermediate ancestor) reverted -> descendant movement REJECTED."""
    root = _build_tree(parent_reverted=True)
    decoded = decode_trace_calls(root, _empty_registry())
    movements = extract_erc20_transfer_calls(
        decoded_calls=decoded, token_address=LINK, receipts_by_tx={TX: _receipt(1)}
    )
    assert movements == [], "parent revert must propagate to descendant"


def test_h4_grandparent_revert_rejects_descendant() -> None:
    """Grandparent reverted but parent and leaf succeeded -> movement STILL
    REJECTED. This is the case the old `parent.success`-only check missed.
    (the trace-success invariant: ANY ancestor revert disqualifies the descendant.)"""
    root = _build_tree(grandparent_reverted=True)
    decoded = decode_trace_calls(root, _empty_registry())
    movements = extract_erc20_transfer_calls(
        decoded_calls=decoded, token_address=LINK, receipts_by_tx={TX: _receipt(1)}
    )
    assert movements == [], "grandparent revert must propagate to descendant"


def test_h4_top_level_tx_revert_rejects_movement() -> None:
    """receipt.status == 0 -> no movements, even if every internal frame
    succeeded."""
    root = _build_tree()
    decoded = decode_trace_calls(root, _empty_registry())
    movements = extract_erc20_transfer_calls(
        decoded_calls=decoded, token_address=LINK, receipts_by_tx={TX: _receipt(0)}
    )
    assert movements == [], "reverted top-level tx must contribute zero movements"


def test_h4_leaf_revert_rejects_movement() -> None:
    """The leaf call itself reverted -> REJECTED."""
    root = _build_tree(leaf_reverted=True)
    decoded = decode_trace_calls(root, _empty_registry())
    movements = extract_erc20_transfer_calls(
        decoded_calls=decoded, token_address=LINK, receipts_by_tx={TX: _receipt(1)}
    )
    assert movements == []


def test_h4_parent_success_flag_propagates_through_decode_trace_calls() -> None:
    """White-box check: a real RawTrace tree fed through `decode_trace_calls`
    yields a DecodedCall whose `parent_success` reflects ALL ancestors' state."""
    # All success: leaf.parent_success == True
    root_ok = _build_tree()
    decoded_ok = decode_trace_calls(root_ok, _empty_registry())
    leaf_ok = next(c for c in decoded_ok if c.trace_address == [0, 0, 0])
    assert leaf_ok.parent_success is True
    assert leaf_ok.success is True

    # Grandparent revert: leaf.parent_success == False
    root_gp = _build_tree(grandparent_reverted=True)
    decoded_gp = decode_trace_calls(root_gp, _empty_registry())
    leaf_gp = next(c for c in decoded_gp if c.trace_address == [0, 0, 0])
    assert leaf_gp.parent_success is False


# --- Cheap synthetic tests preserved for redundancy -----------------------


def _decoded_transfer_call(
    trace_address: list[int],
    success: bool,
    parent_success: bool,
) -> DecodedCall:
    return DecodedCall(
        raw_trace_call_id=f"trace|{trace_address}",
        chain_id=1,
        block_number=18_000_000,
        tx_hash=TX,
        trace_address=trace_address,
        contract_address=LINK,
        method_name="transfer",
        method_selector=ERC20_TRANSFER_SELECTOR,
        params={"to": "0x" + "22" * 20, "amount": 100, "from": "0x" + "11" * 20},
        success=success,
        parent_success=parent_success,
    )


def test_h4_top_level_revert_rejects_movement_synthetic() -> None:
    """receipt.status == 0 -> movement REJECTED via the synthetic path too."""
    call = _decoded_transfer_call(trace_address=[0], success=True, parent_success=True)
    movements = extract_erc20_transfer_calls(
        decoded_calls=[call], token_address=LINK, receipts_by_tx={TX: _receipt(0)}
    )
    assert movements == []


def test_h4_no_receipt_rejects_movement() -> None:
    """If we have no receipt for the tx, we cannot prove status==1 -> REJECT."""
    call = _decoded_transfer_call(trace_address=[0], success=True, parent_success=True)
    movements = extract_erc20_transfer_calls(
        decoded_calls=[call], token_address=LINK, receipts_by_tx={}
    )
    assert movements == []
