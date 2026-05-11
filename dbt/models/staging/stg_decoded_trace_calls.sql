{{ config(materialized='view') }}

-- All decoded internal calls (Python output). Includes call success and
-- parent_success already evaluated. Used for slashing trace reconciliation.
--
-- Local target (DuckDB): seeds carry the same DecodedCall rows.

{% if target.type == 'duckdb' %}
SELECT
    dtc.raw_trace_call_id,
    dtc.chain_id,
    dtc.block_number,
    dtc.tx_hash,
    dtc.trace_address,
    {{ lower_address('dtc.contract_address') }} AS contract_address,
    dtc.method_name,
    dtc.method_selector,
    dtc.params,
    dtc.success,
    dtc.parent_success,
    dtc.run_partition_id
FROM {{ ref('seed_decoded_trace_calls') }} dtc
INNER JOIN {{ ref('stg_canonical_blocks') }} cb
    ON dtc.chain_id = cb.chain_id
   AND dtc.block_number = cb.block_number
{% else %}
SELECT
    dtc.raw_trace_call_id,
    dtc.chain_id,
    dtc.block_number,
    dtc.tx_hash,
    dtc.trace_address,
    {{ lower_address('dtc.contract_address') }} AS contract_address,
    dtc.method_name,
    dtc.method_selector,
    dtc.params,
    dtc.success,
    dtc.parent_success,
    dtc.run_partition_id
FROM {{ source('raw_external', 'decoded_trace_calls') }} dtc
INNER JOIN {{ ref('stg_canonical_blocks') }} cb
    ON dtc.chain_id = cb.chain_id
   AND dtc.block_number = cb.block_number
{% endif %}
