{{ config(materialized='view') }}

-- Pass-through projection of the raw_logs external table. Python ingestion
-- writes parquet → BQ external table; this model exposes it without
-- modification (no decoding here — that's authoritative in Python).
--
-- Local target (DuckDB): seeds already carry the LINK Transfer raw_log rows
-- the staging models need.

{% if target.type == 'duckdb' %}
SELECT
    chain_id,
    block_number,
    block_hash,
    tx_hash,
    tx_index,
    log_index,
    {{ lower_address('address') }} AS address,
    topics,
    data,
    run_partition_id,
    ingested_at
FROM {{ ref('seed_link_transfers') }}
{% else %}
SELECT
    chain_id,
    block_number,
    block_hash,
    tx_hash,
    tx_index,
    log_index,
    {{ lower_address('address') }} AS address,
    topics,
    data,
    run_partition_id,
    ingested_at
FROM {{ source('raw_external', 'raw_logs') }}
{% endif %}
