{{ config(materialized='incremental', unique_key='movement_id', incremental_strategy='merge') }}

-- Canonical TokenMovements (Python output of `unify_movements`). Both
-- log-sourced and trace-sourced movements unified; evidence_ids preserved.
--
-- Local target (DuckDB): seeds carry the same TokenMovement rows.

{% if target.type == 'duckdb' %}
SELECT
    movement_id,
    chain_id,
    block_number,
    tx_hash,
    {{ lower_address('token_address') }} AS token_address,
    {{ lower_address('from_addr') }} AS from_addr,
    {{ lower_address('to_addr') }} AS to_addr,
    amount,
    evidence_ids,
    source_priority,
    is_canonical,
    run_partition_id
FROM {{ ref('seed_token_movements') }}
{% if is_incremental() %}
WHERE {{ incremental_block_predicate('block_number') }}
{% endif %}
{% else %}
SELECT
    movement_id,
    chain_id,
    block_number,
    tx_hash,
    {{ lower_address('token_address') }} AS token_address,
    {{ lower_address('from_addr') }} AS from_addr,
    {{ lower_address('to_addr') }} AS to_addr,
    amount,
    evidence_ids,
    source_priority,
    is_canonical,
    run_partition_id
FROM {{ source('raw_external', 'token_movements') }}
{% if is_incremental() %}
WHERE {{ incremental_block_predicate('block_number') }}
{% endif %}
{% endif %}
