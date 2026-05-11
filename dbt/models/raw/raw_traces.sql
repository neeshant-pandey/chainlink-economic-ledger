{{ config(materialized='view') }}

-- Passthrough of the raw traces parquet ingested by Python. Tree
-- reconstruction lives in `decoder.trace_tree`; this model is intentionally
-- a flat row-per-frame view.
--
-- Local target (DuckDB): the trace decoding happens in Python (in
-- `scripts/seed_to_local.py`); the dbt model just exposes the resulting
-- decoded calls. We keep this model present (empty) so dbt graph stays whole.
{% if target.type == 'duckdb' %}
SELECT
    CAST(NULL AS VARCHAR) AS tx_hash,
    CAST(NULL AS BIGINT) AS block_number,
    CAST(NULL AS VARCHAR) AS trace_address,
    CAST(NULL AS VARCHAR) AS run_partition_id
WHERE FALSE
{% else %}
SELECT * FROM {{ source('raw_external', 'raw_traces') }}
{% endif %}
