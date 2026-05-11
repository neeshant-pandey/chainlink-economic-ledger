{{ config(materialized='view') }}

-- Passthrough of raw balance snapshots ingested by Python.
--
-- Local target (DuckDB): no balance snapshots are sourced from fixtures
-- (the golden tx fixtures only carry tx + receipt + logs + trace, not pool
-- balance snapshots). We emit an empty SELECT shaped like the BQ source so
-- downstream models keep compiling.
{% if target.type == 'duckdb' %}
SELECT
    CAST(NULL AS INTEGER) AS chain_id,
    CAST(NULL AS BIGINT) AS block_number,
    CAST(NULL AS VARCHAR) AS token_address,
    CAST(NULL AS VARCHAR) AS holder_address,
    CAST(NULL AS DECIMAL(38,0)) AS balance,
    CAST(NULL AS VARCHAR) AS run_partition_id
WHERE FALSE
{% else %}
SELECT * FROM {{ source('raw_external', 'raw_balance_snapshots') }}
{% endif %}
