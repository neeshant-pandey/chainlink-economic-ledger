{{ config(materialized='view') }}

-- Decoded entry-point calls into the staking pool (top-level tx calldata
-- decoded by `decoder.calldata_decoder`). Used to enrich actions with
-- caller intent. Selected from decoded_trace_calls where the call is at
-- trace_address [] (the top-level tx) AND addressed to a registered
-- staking pool.
--
-- Local target: trace_address arrives as a JSON-array-string in the seed
-- (DuckDB's CSV loader doesn't natively unpack list types). We compare
-- against the literal "[]" string instead of array length.

{% if target.type == 'duckdb' %}
SELECT
    raw_trace_call_id,
    chain_id,
    block_number,
    tx_hash,
    trace_address,
    contract_address,
    method_name,
    method_selector,
    params,
    success,
    run_partition_id
FROM {{ ref('stg_decoded_trace_calls') }}
WHERE trace_address = '[]'
  AND method_name IN ('stake', 'unbond', 'claimReward', 'unstake', 'migrate')
{% else %}
SELECT
    raw_trace_call_id,
    chain_id,
    block_number,
    tx_hash,
    trace_address,
    contract_address,
    method_name,
    method_selector,
    params,
    success,
    run_partition_id
FROM {{ ref('stg_decoded_trace_calls') }}
WHERE ARRAY_LENGTH(trace_address) = 0
  AND method_name IN ('stake', 'unbond', 'claimReward', 'unstake', 'migrate')
{% endif %}
