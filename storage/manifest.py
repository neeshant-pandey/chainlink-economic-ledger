"""Per-write data manifests. Each parquet file produced by `dataset_writer`
is recorded with row count, byte size, source, and the `run_partition_id`
that produced it.

Manifests are written as JSON next to the parquet (`*.manifest.json`) AND
aggregated into a manifests table in BigQuery via `lineage/source_manifest.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self


@dataclass
class _ManifestPayload:
    run_id: str
    run_partition_id: str
    source: str
    partition_key: str
    gcs_paths: list[str]
    row_counts: dict[str, int]
    total_rows: int = field(default=0)


class Manifest:
    """Per-write manifest. Construct via `Manifest.create(...)` then
    `persist(...)`."""

    def __init__(self, payload: _ManifestPayload) -> None:
        self._payload = payload

    @classmethod
    def create(
        cls,
        run_id: str,
        run_partition_id: str,
        source: str,
        partition_key: str,
        gcs_paths: list[str],
        row_counts: dict[str, int],
    ) -> Self:
        total = sum(row_counts.values())
        return cls(
            _ManifestPayload(
                run_id=run_id,
                run_partition_id=run_partition_id,
                source=source,
                partition_key=partition_key,
                gcs_paths=list(gcs_paths),
                row_counts=dict(row_counts),
                total_rows=total,
            )
        )

    def persist(self, target: str) -> None:
        """Writes JSON manifest to `target` (gs:// URI or local path).

        Local fallback used by unit tests; production wires to GCS.
        """
        body = json.dumps(self._payload.__dict__, indent=2)
        if target.startswith("gs://"):
            from google.cloud.storage import Client  # type: ignore[import-untyped]

            without_scheme = target[len("gs://") :]
            bucket_name, _, object_name = without_scheme.partition("/")
            client = Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(object_name)
            blob.upload_from_string(body, content_type="application/json")
        else:
            p = Path(target)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)

    @classmethod
    def load(cls, target: str) -> Self:
        if target.startswith("gs://"):
            from google.cloud.storage import Client

            without_scheme = target[len("gs://") :]
            bucket_name, _, object_name = without_scheme.partition("/")
            client = Client()
            bucket = client.bucket(bucket_name)
            data = bucket.blob(object_name).download_as_text()
        else:
            data = Path(target).read_text()
        body = json.loads(data)
        return cls(_ManifestPayload(**body))

    def total_rows(self) -> int:
        return self._payload.total_rows

    @property
    def run_partition_id(self) -> str:
        return self._payload.run_partition_id

    @property
    def source(self) -> str:
        return self._payload.source

    @property
    def gcs_paths(self) -> list[str]:
        return list(self._payload.gcs_paths)
