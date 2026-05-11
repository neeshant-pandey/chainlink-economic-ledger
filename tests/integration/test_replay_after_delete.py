"""Replay-after-delete: snapshot, delete partition rows + parquet, replay, assert
identical outputs to the snapshot."""

import pytest

pytestmark = pytest.mark.integration


def test_replay_after_delete_produces_identical_marts() -> None:
    """The proof that delete-then-replay is safe. Mart hashes (excluding
    run_partition_id) match pre-delete snapshot."""
    pytest.skip(
        "Integration test — requires live BQ + GCS writes (delete partition "
        "+ replay path). Phase 6 stretch per docs/reproduction.md. The "
        "in-memory equivalent (replay produces identical entity IDs across "
        "different run_partition_ids) is covered by "
        "tests/unit/test_replay_idempotency.py."
    )
