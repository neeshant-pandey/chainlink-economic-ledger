"""GCS → BigQuery loads and partition-scoped MERGEs.

Two operations:
  - `load_parquet_to_bq`: append-only load into a staging table (one parquet →
    one load job). Used for raw layer ingestion.
  - `merge_to_table`: MERGE staging into target by `merge_keys` (stable entity
    IDs only). Used for incremental marts and replay-safe upserts.

Note: dbt incremental models handle their own MERGE via
`incremental_strategy='merge'`; this module is for the raw → BQ hand-off only
(before dbt runs). The Google BQ client is imported lazily.

Per the Airflow adapter convention, this module replaces a hypothetical `LoadToBigQueryOperator`
in Airflow — operators delegate here rather than reimplementing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from decoder.types import LoadResult, MergeResult


def load_parquet_to_bq(
    gcs_path: str,
    table: str,
    partition_field: str | None,
    cluster_fields: list[str] | None,
    write_disposition: str = "WRITE_APPEND",
) -> LoadResult:
    """`gcs_path` may be a glob (`gs://b/p/*.parquet`). `partition_field` and
    `cluster_fields` are no-ops if the table already exists with a fixed
    schema.

    Caller is responsible for ensuring the table exists with the right schema
    — use `create_table_from_schema` first.
    """
    from google.cloud import bigquery  # lazy

    client = bigquery.Client()
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=write_disposition,
        autodetect=False,
    )
    load_job = client.load_table_from_uri(gcs_path, table, job_config=job_config)
    load_job.result()  # waits

    # Compute byte count from the destination table after the load
    table_obj = client.get_table(table)
    return LoadResult(
        table=table,
        rows_loaded=int(load_job.output_rows or 0),
        bytes_loaded=int(table_obj.num_bytes or 0),
    )


def merge_to_table(
    staging_table: str,
    target_table: str,
    merge_keys: list[str],
) -> MergeResult:
    """MERGE on stable entity IDs only. `run_partition_id` is updated as a
    column, NOT included in `merge_keys`.

    Generates a parameterized MERGE statement with positional column lists
    inferred from the target table schema.
    """
    from google.cloud import bigquery

    client = bigquery.Client()
    table_obj = client.get_table(target_table)
    columns = [f.name for f in table_obj.schema]
    update_cols = [c for c in columns if c not in merge_keys]

    on_clause = " AND ".join(f"T.{k} = S.{k}" for k in merge_keys)
    update_clause = ", ".join(f"T.{c} = S.{c}" for c in update_cols)
    insert_columns = ", ".join(columns)
    insert_values = ", ".join(f"S.{c}" for c in columns)

    sql = (
        f"MERGE `{target_table}` T USING `{staging_table}` S "
        f"ON {on_clause} "
        f"WHEN MATCHED THEN UPDATE SET {update_clause} "
        f"WHEN NOT MATCHED THEN INSERT ({insert_columns}) VALUES ({insert_values})"
    )
    job = client.query(sql)
    job.result()
    stats = job.dml_stats
    return MergeResult(
        target_table=target_table,
        rows_inserted=int(getattr(stats, "inserted_row_count", 0) or 0),
        rows_updated=int(getattr(stats, "updated_row_count", 0) or 0),
        rows_deleted=int(getattr(stats, "deleted_row_count", 0) or 0),
    )


def create_table_from_schema(table: str, schema_path: str) -> None:
    """Idempotent table create from JSON schema. Schemas live under
    `dbt/models/raw/*.yml`; we accept either a JSON path with the BQ-shaped
    schema or a YAML path, but only JSON is parsed here.
    """
    from google.cloud import bigquery

    payload = json.loads(Path(schema_path).read_text())
    schema = []
    for col in payload.get("fields", payload):
        schema.append(
            bigquery.SchemaField(
                col["name"],
                col["type"],
                mode=col.get("mode", "NULLABLE"),
            )
        )
    client = bigquery.Client()
    table_ref = bigquery.TableReference.from_string(table)
    bq_table = bigquery.Table(table_ref, schema=schema)
    try:
        client.create_table(bq_table)
    except Exception as exc:  # noqa: BLE001
        if "Already Exists" in str(exc):
            return
        raise


def _build_query_params(params: dict[str, Any] | None) -> list[Any]:
    """Translate a dict of named params into BigQuery ScalarQueryParameter
    objects. Local helper kept here to avoid duplicating the BQClient logic
    when this module is invoked outside of `ingestion/bq/`.
    """
    if not params:
        return []
    from google.cloud import bigquery

    out: list[Any] = []
    for name, value in params.items():
        if isinstance(value, int):
            out.append(bigquery.ScalarQueryParameter(name, "INT64", value))
        else:
            out.append(bigquery.ScalarQueryParameter(name, "STRING", str(value)))
    return out
