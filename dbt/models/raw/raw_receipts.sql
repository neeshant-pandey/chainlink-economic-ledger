{{ config(materialized='view') }}

-- Passthrough of raw receipts ingested by Python.
--
-- Local target: no downstream models reference raw_receipts; empty shape
-- preserves graph completeness.
{% if target.type == 'duckdb' %}
SELECT
    CAST(NULL AS VARCHAR) AS tx_hash,
    CAST(NULL AS INTEGER) AS status,
    CAST(NULL AS VARCHAR) AS run_partition_id
WHERE FALSE
{% else %}
SELECT * FROM {{ source('raw_external', 'raw_receipts') }}
{% endif %}
