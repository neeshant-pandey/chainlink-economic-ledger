"""Failed/reverted tx must produce zero TokenMovements even if internal calls
appear successful in trace output."""

import pytest

pytestmark = pytest.mark.integration


def test_reverted_tx_produces_no_movements() -> None:
    """A tx with receipt.status=0 → no TokenMovements regardless of trace contents.
    Tests the receipt-aware filter in `extract_erc20_transfer_calls`."""
    pytest.skip(
        "Integration test — requires a real reverted-tx fixture pulled from "
        "live RPC. The receipt-aware filter is unit-tested in "
        "tests/unit/test_movement_builder_ancestor.py (synthetic but real "
        "RawTrace tree with grandparent revert; asserts movement is "
        "rejected). Phase 6 stretch: pull a real reverted tx from mainnet."
    )
