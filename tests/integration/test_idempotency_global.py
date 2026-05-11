"""Global idempotency: replay the same range, all 7 ID grains hash-identical."""

import pytest

pytestmark = pytest.mark.integration


def test_idempotency_all_seven_grains() -> None:
    """After two runs of the same partition with distinct run_partition_ids:
    - raw_log_id sets identical
    - decoded_event_id sets identical
    - raw_trace_call_id sets identical
    - movement_id sets identical
    - action_id sets identical
    - ledger_entry_id sets identical
    - run_partition_id values DIFFER between the two runs (lineage signal)
    - All mart hashes identical when computed without run_partition_id
    """
    pytest.skip(
        "Integration test — requires live BQ writes for the 7-grain hash "
        "comparison. Phase 6 stretch per docs/reproduction.md. The 6 entity "
        "ID grains are exercised at unit level via test_id_determinism.py "
        "(subprocess-based, asserts byte-identical IDs across replays)."
    )
