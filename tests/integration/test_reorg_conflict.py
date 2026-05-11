"""Reorg conflict: simulate a block_hash change between shadow ingestion and
finalization. Assert the conflict is recorded and the affected partition is
queued for replay."""

import pytest

pytestmark = pytest.mark.integration


def test_reorg_conflict_records_event_and_queues_replay() -> None:
    """Use the synthetic fixture in tests/fixtures/known_reorg.json:
    1. Ingest shadow with hash A
    2. Move chain head; simulate finalization with hash B
    3. promote_finalized_blocks should record one ReorgEvent
    4. mark_partition_for_replay should be invoked
    5. Subsequent run should re-ingest the affected range
    """
    pytest.skip(
        "Integration test — requires live ingestion/finalization runtime. "
        "Phase 6 stretch per docs/reproduction.md. Reorg model is covered "
        "structurally by stg_canonical_blocks / stg_shadow_tip_blocks dbt "
        "models and unit-tested via test_replay_idempotency.py."
    )
