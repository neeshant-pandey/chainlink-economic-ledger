"""Source manifest table — what was ingested, by which run, into which paths.

Companion to `storage/manifest.py`. The latter writes per-file manifests as JSON;
this module aggregates them into the BigQuery `source_manifests` table for
queryable lineage.
"""

from __future__ import annotations

from decoder.types import RunLineage, SourceRecord


def record_source(
    run_id: str,
    source_name: str,
    chain_id: int,
    partition_key: str,
    gcs_paths: list[str],
    rows: int,
    watermark_block: int,
) -> None:
    """Idempotent: same (run_id, source_name, partition_key) overwrites prior row."""
    raise NotImplementedError(
        "Planned production lineage sink: persist source manifests to BigQuery or "
        "another queryable metadata store."
    )


def get_sources_for_run(run_id: str) -> list[SourceRecord]:
    raise NotImplementedError(
        "Planned production lineage sink: read source manifests from the metadata store."
    )


def get_run_lineage(run_id: str) -> RunLineage:
    """Joins run metadata + all source records for the run."""
    raise NotImplementedError(
        "Planned production lineage sink: join run metadata with source manifests."
    )
