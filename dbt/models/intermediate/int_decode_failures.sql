{{ config(materialized='incremental', unique_key='raw_id', incremental_strategy='merge') }}

-- Persisted decode failures (Python-written to GCS). Surfaces ABI drift and
-- unregistered contracts. Powers `assert_unknown_signatures_below_threshold`.
--
-- Local target (DuckDB): no decode failures are produced over the golden
-- fixtures (every event signature on every contract is known). We expose an
-- empty shape so downstream models compile and the unknown-signature
-- threshold test passes trivially (count = 0).

{% if target.type == 'duckdb' %}
SELECT
    CAST(NULL AS VARCHAR) AS raw_id,
    CAST(NULL AS VARCHAR) AS failure_reason,
    CAST(NULL AS VARCHAR) AS failure_detail,
    CAST(NULL AS VARCHAR) AS contract_address,
    CAST(NULL AS VARCHAR) AS topic0,
    CAST(NULL AS INTEGER) AS chain_id,
    CAST(NULL AS BIGINT) AS block_number,
    CAST(NULL AS VARCHAR) AS tx_hash,
    CAST(NULL AS VARCHAR) AS run_partition_id
WHERE FALSE
{% else %}
SELECT
    raw_id,
    failure_reason,
    failure_detail,
    contract_address,
    topic0,
    chain_id,
    block_number,
    tx_hash,
    run_partition_id
FROM {{ source('raw_external', 'decode_failures') }}
{% if is_incremental() %}
WHERE {{ incremental_block_predicate('block_number') }}
{% endif %}
{% endif %}
