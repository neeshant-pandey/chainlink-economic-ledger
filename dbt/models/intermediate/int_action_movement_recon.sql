{{ config(materialized='incremental', unique_key='tx_hash', incremental_strategy='merge') }}

-- Tx-level reconciliation aggregates over Python-produced edges. NOT a
-- passthrough: this model adds tx-level rollups on top of
-- stg_action_movement_edges.
SELECT
    tx_hash,
    chain_id,
    block_number,
    {{ countif("status = 'exact'") }}         AS exact_count,
    {{ countif("status = 'partial'") }}       AS partial_count,
    {{ countif("status = 'unmatched'") }}     AS unmatched_count,
    {{ countif("status = 'not_expected'") }}  AS not_expected_count,
    {{ countif("status = 'unexpected'") }}    AS unexpected_count,
    {{ countif("status = 'ambiguous'") }}     AS ambiguous_count,
    COUNT(*) AS edge_count,
    CASE
        WHEN {{ countif("status IN ('unmatched', 'unexpected', 'ambiguous')") }} > 0 THEN 'fail'
        WHEN {{ countif("status = 'partial'") }} > 0 THEN 'warn'
        ELSE 'ok'
    END AS overall_status,
    MAX(run_partition_id) AS run_partition_id
FROM {{ ref('stg_action_movement_edges') }}
GROUP BY tx_hash, chain_id, block_number
