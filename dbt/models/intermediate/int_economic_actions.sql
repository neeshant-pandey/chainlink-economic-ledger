{{ config(materialized='incremental', unique_key='action_id', incremental_strategy='merge') }}

-- Economic actions, written by Python (`protocols.staking_v02.semantics`).
-- This model exposes them with canonical-block filtering and the
-- incremental_block_predicate for replay safety.
--
-- Local target (DuckDB): seeds carry the same action rows produced by the
-- real Python pipeline run via scripts/seed_to_local.py.

{% if target.type == 'duckdb' %}
SELECT
    a.action_id,
    a.kind,
    a.chain_id,
    a.block_number,
    a.tx_hash,
    a.log_index,
    {{ lower_address('a.contract_address') }} AS contract_address,
    a.pool_role,
    {{ lower_address('a.wallet') }} AS wallet,
    a.amount_link,
    a.source_event_signature,
    a.raw_log_id,
    a.decoded_event_id,
    a.run_partition_id
FROM {{ ref('seed_economic_actions') }} a
INNER JOIN {{ ref('stg_canonical_blocks') }} cb
    ON a.chain_id = cb.chain_id
   AND a.block_number = cb.block_number
{% if is_incremental() %}
WHERE {{ incremental_block_predicate('a.block_number') }}
{% endif %}
{% else %}
SELECT
    a.action_id,
    a.kind,
    a.chain_id,
    a.block_number,
    a.tx_hash,
    a.log_index,
    {{ lower_address('a.contract_address') }} AS contract_address,
    a.pool_role,
    {{ lower_address('a.wallet') }} AS wallet,
    a.amount_link,
    a.source_event_signature,
    a.raw_log_id,
    a.decoded_event_id,
    a.run_partition_id
FROM {{ source('raw_external', 'economic_actions') }} a
INNER JOIN {{ ref('stg_canonical_blocks') }} cb
    ON a.chain_id = cb.chain_id
   AND a.block_number = cb.block_number
{% if is_incremental() %}
WHERE {{ incremental_block_predicate('a.block_number') }}
{% endif %}
{% endif %}
