"""Defensive: malformed input with duplicate log_index in a single tx must be
rejected (not silently deduped)."""

import pytest

pytestmark = pytest.mark.integration


def test_duplicate_log_index_in_tx_raises() -> None:
    """Two RawLogs with identical (chain_id, block_number, tx_hash, log_index) in
    a single ingestion batch → pipeline fails with a clear error, not silent
    deduplication."""
    pytest.skip(
        "Integration test — requires live ingestion/storage runtime. Phase 6 "
        "stretch per docs/reproduction.md. Determinism-invariant equivalent "
        "covered at unit level by test_id_determinism.py."
    )
