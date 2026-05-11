"""public-function coverage for previously-untested logic.

Additional coverage for public functions:
  - decoder.trace_tree.assign_trace_addresses
  - protocols.payment_abstraction.semantics.is_pa_contract_address (now also
    in test_golden_pa_decoding.py)
  - protocols.payment_abstraction.semantics.pa_role_of (now also in
    test_golden_pa_decoding.py)
  - reconciliation.economic_reconciler.write_reconciliation_outputs
  - storage.dataset_writer.* public writers
  - storage.manifest.Manifest public methods (create, persist, load,
    total_rows, run_partition_id, source, gcs_paths)

Each function below:
  1. Is called with realistic input.
  2. Asserts the return type matches the function signature.
  3. Asserts at least one docstring-promised value (path content, idempotency,
     ordering, ...).
"""

from __future__ import annotations

from pathlib import Path

from decoder.trace_tree import assign_trace_addresses
from decoder.types import RawTrace

# ---------------------------------------------------------------------------
# decoder.trace_tree.assign_trace_addresses
# ---------------------------------------------------------------------------


def _leaf(
    tx_hash: str = "0xt",
    block_number: int = 1,
    chain_id: int = 1,
    to_addr: str = "0xaa",
) -> RawTrace:
    return RawTrace(
        chain_id=chain_id,
        block_number=block_number,
        tx_hash=tx_hash,
        type="CALL",
        from_addr="0xfrom",
        to_addr=to_addr,
        value=0,
        gas=0,
        gas_used=0,
        input_data="0x",
        output="0x",
        error=None,
        revert_reason=None,
        calls=[],
        trace_address=[],
    )


def test_assign_trace_addresses_root_gets_empty_list() -> None:
    """Per the docstring: 'The root receives [].'"""
    node = _leaf()
    result = assign_trace_addresses(node)
    assert isinstance(result, RawTrace)
    assert result.trace_address == []


def test_assign_trace_addresses_children_get_parent_plus_index() -> None:
    """Per the docstring: 'child[i] receives parent_addr + [i]'."""
    leaf_a = _leaf(to_addr="0xa")
    leaf_b = _leaf(to_addr="0xb")
    leaf_c = _leaf(to_addr="0xc")
    root = RawTrace(
        chain_id=1,
        block_number=1,
        tx_hash="0xt",
        type="CALL",
        from_addr="0xfrom",
        to_addr="0xroot",
        value=0,
        gas=0,
        gas_used=0,
        input_data="0x",
        output="0x",
        error=None,
        revert_reason=None,
        calls=[leaf_a, leaf_b, leaf_c],
        trace_address=[],
    )
    out = assign_trace_addresses(root)
    assert out.trace_address == []
    assert [c.trace_address for c in out.calls] == [[0], [1], [2]]


def test_assign_trace_addresses_nested_deeply() -> None:
    """A 3-deep tree gets [], [0], [0,0], [0,0,0]."""
    deepest = _leaf(to_addr="0xdeepest")
    middle = RawTrace(
        chain_id=1,
        block_number=1,
        tx_hash="0xt",
        type="CALL",
        from_addr="0xf",
        to_addr="0xmid",
        value=0,
        gas=0,
        gas_used=0,
        input_data="0x",
        output="0x",
        error=None,
        revert_reason=None,
        calls=[deepest],
        trace_address=[],
    )
    child = RawTrace(
        chain_id=1,
        block_number=1,
        tx_hash="0xt",
        type="CALL",
        from_addr="0xf",
        to_addr="0xchild",
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
    root = RawTrace(
        chain_id=1,
        block_number=1,
        tx_hash="0xt",
        type="CALL",
        from_addr="0xf",
        to_addr="0xroot",
        value=0,
        gas=0,
        gas_used=0,
        input_data="0x",
        output="0x",
        error=None,
        revert_reason=None,
        calls=[child],
        trace_address=[],
    )
    out = assign_trace_addresses(root)
    assert out.trace_address == []
    assert out.calls[0].trace_address == [0]
    assert out.calls[0].calls[0].trace_address == [0, 0]
    assert out.calls[0].calls[0].calls[0].trace_address == [0, 0, 0]


def test_assign_trace_addresses_preserves_fields() -> None:
    """The function rebuilds nodes (RawTrace is frozen) but other fields are
    preserved."""
    node = _leaf(to_addr="0xpreserved")
    out = assign_trace_addresses(node)
    assert out.to_addr == "0xpreserved"
    assert out.chain_id == node.chain_id
    assert out.tx_hash == node.tx_hash


# ---------------------------------------------------------------------------
# reconciliation.economic_reconciler.write_reconciliation_outputs
# ---------------------------------------------------------------------------


def test_write_reconciliation_outputs_writes_edges_locally(tmp_path: Path) -> None:
    """Per the docstring: writes edges.json next to the requested path; returns a
    WriteResult carrying the rows count (len(edges) + len(tx_recons) + 1)."""
    import json

    from decoder.types import WriteResult
    from reconciliation.economic_reconciler import (
        ActionMovementMatch,
        Method,
        PartitionReconciliation,
        Status,
        TxReconciliation,
        write_reconciliation_outputs,
    )

    edges = [
        ActionMovementMatch(
            edge_id="e1",
            action_id="a1",
            movement_id="m1",
            allocated_amount=100,
            status=Status.EXACT,
            method=Method.EVENT_LOG,
            reason="exact match",
        ),
        ActionMovementMatch(
            edge_id="e2",
            action_id="a2",
            movement_id=None,
            allocated_amount=0,
            status=Status.UNMATCHED,
            method=None,
            reason="no movements",
        ),
    ]
    tx_recons = [
        TxReconciliation(
            chain_id=1,
            block_number=10,
            tx_hash="0xt",
            edges=edges,
            actions_total=2,
            movements_total=1,
            unmatched_actions=1,
            unexpected_movements=0,
            overall_status=Status.PARTIAL,
        )
    ]
    partition = PartitionReconciliation(
        partition_id="p|1|10|10",
        chain_id=1,
        block_range=(10, 10),
        tx_recons=tx_recons,
        pass_rate=0.5,
        counts_by_status={Status.EXACT: 1, Status.UNMATCHED: 1},
    )

    out_dir = tmp_path / "recon_out"
    result = write_reconciliation_outputs(
        edges=edges,
        tx_recons=tx_recons,
        partition_recon=partition,
        gcs_path=str(out_dir),
        run_partition_id="run_abc",
    )

    assert isinstance(result, WriteResult)
    assert result.run_partition_id == "run_abc"
    # rows = len(edges) + len(tx_recons) + 1
    assert result.rows == len(edges) + len(tx_recons) + 1
    # edges.json was written locally with all rows
    edges_path = out_dir / "edges.json"
    assert edges_path.exists()
    body = json.loads(edges_path.read_text())
    assert len(body) == len(edges)
    assert {e["edge_id"] for e in body} == {"e1", "e2"}
    # Run partition id is stamped on every row.
    for e in body:
        assert e["run_partition_id"] == "run_abc"
    # First row carries status / method / allocated_amount per the docstring.
    e1 = next(e for e in body if e["edge_id"] == "e1")
    assert e1["status"] == "exact"
    assert e1["method"] == "event_log"
    assert e1["allocated_amount"] == 100


# ---------------------------------------------------------------------------
# storage.dataset_writer -- public writers
# ---------------------------------------------------------------------------


def test_write_logs_parquet_writes_locally(tmp_path: Path) -> None:
    """Per the module docstring: 'When gcs_path starts with gs://, we use the
    google.cloud.storage client. Otherwise we treat it as a local path (handy
    for unit tests and the repro.sh --fixture-only path).'

    Realistic input: a single RawLog; expect a JSON-lines file containing the
    serialized log plus the run_partition_id and ingested_at columns.
    """
    import json

    from decoder.types import RawLog, WriteResult
    from storage.dataset_writer import write_logs_parquet

    log = RawLog(
        chain_id=1,
        block_number=18_671_459,
        block_hash="0x1234",
        tx_hash="0xabcd",
        tx_index=1,
        log_index=0,
        address="0x514910771af9ca656af840dff83e8264ecf986ca",
        topics=["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"],
        data="0x00",
    )

    result = write_logs_parquet(
        logs=[log],
        gcs_path=str(tmp_path),
        run_partition_id="rp1",
    )
    assert isinstance(result, WriteResult)
    assert result.run_partition_id == "rp1"
    assert result.rows == 1
    # Local fallback file written
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    body = files[0].read_text().strip().split("\n")
    assert len(body) == 1
    row = json.loads(body[0])
    assert row["block_number"] == 18_671_459
    assert row["run_partition_id"] == "rp1"
    assert "ingested_at" in row


def test_write_decode_failures_parquet_writes_failure_rows(tmp_path: Path) -> None:
    """Per the docstring: 'Persist every failed DecodeResult so dbt's
    int_decode_failures and the unknown-signature monitor can detect ABI drift
    and unregistered contracts.'"""
    import json

    from decoder.types import DecodeResult
    from storage.dataset_writer import write_decode_failures_parquet

    fail = DecodeResult(
        raw_id="raw1",
        success=False,
        decoded=None,
        failure_reason="unknown_topic",
        failure_detail="topic0 0xdeadbeef not in ABI",
    )
    result = write_decode_failures_parquet(
        failures=[fail],
        gcs_path=str(tmp_path),
        run_partition_id="rp_fail",
    )
    assert result.rows == 1
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    row = json.loads(files[0].read_text().strip().split("\n")[0])
    assert row["raw_id"] == "raw1"
    assert row["success"] is False
    assert row["failure_reason"] == "unknown_topic"
    assert row["run_partition_id"] == "rp_fail"


def test_write_blocks_parquet_appends_run_partition_id(tmp_path: Path) -> None:
    """run_partition_id (lineage column on every row) is stamped on writes."""
    import json

    from decoder.types import Block, BlockHeader
    from storage.dataset_writer import write_blocks_parquet

    header = BlockHeader(
        chain_id=1,
        block_number=100,
        block_hash="0xbbb",
        parent_hash="0xaaa",
        timestamp=1_700_000_000,
        miner="0xminer",
        base_fee_per_gas=10,
    )
    block = Block(header=header, transaction_hashes=["0xtx1"], full_transactions=None)

    result = write_blocks_parquet([block], gcs_path=str(tmp_path), run_partition_id="rp2")
    assert result.rows == 1
    files = list(tmp_path.iterdir())
    row = json.loads(files[0].read_text().strip().split("\n")[0])
    assert row["run_partition_id"] == "rp2"


# ---------------------------------------------------------------------------
# storage.manifest.Manifest -- public methods
# ---------------------------------------------------------------------------


def test_manifest_create_aggregates_total_rows() -> None:
    """Per the docstring: total = sum(row_counts.values()) computed at create."""
    from storage.manifest import Manifest

    m = Manifest.create(
        run_id="r1",
        run_partition_id="rp1",
        source="bq",
        partition_key="2024-01-01",
        gcs_paths=["gs://x/a.parquet", "gs://x/b.parquet"],
        row_counts={"logs": 100, "traces": 50, "blocks": 1},
    )
    assert isinstance(m, Manifest)
    assert m.total_rows() == 151
    assert m.run_partition_id == "rp1"
    assert m.source == "bq"
    assert m.gcs_paths == ["gs://x/a.parquet", "gs://x/b.parquet"]


def test_manifest_persist_and_load_local_roundtrip(tmp_path: Path) -> None:
    """Local-mode persist writes JSON; load reads it back to an equivalent
    Manifest. Per the docstring: 'Local fallback used by unit tests.'"""
    from storage.manifest import Manifest

    m = Manifest.create(
        run_id="r1",
        run_partition_id="rp1",
        source="bq",
        partition_key="2024-01-01",
        gcs_paths=["a.parquet", "b.parquet"],
        row_counts={"logs": 10, "traces": 20},
    )
    target = tmp_path / "subdir" / "manifest.json"
    m.persist(str(target))
    assert target.exists()
    loaded = Manifest.load(str(target))
    assert isinstance(loaded, Manifest)
    assert loaded.run_partition_id == m.run_partition_id
    assert loaded.source == m.source
    assert loaded.total_rows() == m.total_rows()
    assert loaded.gcs_paths == m.gcs_paths


def test_manifest_gcs_paths_returns_copy() -> None:
    """`gcs_paths` should return a list copy -- mutating the returned list must
    not corrupt internal state."""
    from storage.manifest import Manifest

    m = Manifest.create(
        run_id="r1",
        run_partition_id="rp1",
        source="bq",
        partition_key="k",
        gcs_paths=["a", "b"],
        row_counts={"x": 1},
    )
    paths = m.gcs_paths
    paths.append("malicious")
    # Original is unaffected.
    assert m.gcs_paths == ["a", "b"]
