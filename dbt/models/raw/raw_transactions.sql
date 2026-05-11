{{ config(materialized='view') }}

-- Passthrough of raw transactions ingested by Python.
--
-- Local target: no models downstream of raw_transactions exist in this
-- scaffold yet, so we expose an empty shape for graph completeness only.
{% if target.type == 'duckdb' %}
SELECT
    CAST(NULL AS VARCHAR) AS tx_hash,
    CAST(NULL AS BIGINT) AS block_number,
    CAST(NULL AS INTEGER) AS tx_index,
    CAST(NULL AS VARCHAR) AS run_partition_id
WHERE FALSE
{% else %}
SELECT * FROM {{ source('raw_external', 'raw_transactions') }}
{% endif %}
