{{ config(materialized='view') }}

-- Aggregates int_decode_failures by `(contract_address, topic0)` so the
-- unknown-signature monitor can detect the top-N drifting signatures
-- quickly.
{% if target.type == 'duckdb' %}
SELECT
    contract_address,
    topic0,
    COUNT(*) AS occurrences,
    MIN(block_number) AS first_block,
    MAX(block_number) AS last_block,
    -- DuckDB: slice the aggregated array to first 5 elements; FILTER skips NULLs.
    LIST(tx_hash) FILTER (WHERE tx_hash IS NOT NULL)[1:5] AS sample_tx_hashes
FROM {{ ref('int_decode_failures') }}
WHERE failure_reason = 'unknown_topic'
GROUP BY contract_address, topic0
{% else %}
SELECT
    contract_address,
    topic0,
    COUNT(*) AS occurrences,
    MIN(block_number) AS first_block,
    MAX(block_number) AS last_block,
    ARRAY_AGG(tx_hash IGNORE NULLS LIMIT 5) AS sample_tx_hashes
FROM {{ ref('int_decode_failures') }}
WHERE failure_reason = 'unknown_topic'
GROUP BY contract_address, topic0
{% endif %}
