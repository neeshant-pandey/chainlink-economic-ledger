{{ config(materialized='view') }}

-- LINK ERC-20 Transfer events. Filtered to staking-relevant addresses (any
-- pool contract, plus operator/community wallets that interacted with
-- pools). The Python `decoder.event_decoder` already produced these as
-- decoded events with event_name='Transfer' on the LINK contract.
--
-- Local target (DuckDB): seeds carry the same DecodedEvent rows.

{% if target.type == 'duckdb' %}
SELECT
    de.decoded_event_id,
    de.raw_log_id,
    de.chain_id,
    de.block_number,
    de.tx_hash,
    de.log_index,
    {{ lower_address('de.contract_address') }} AS token_address,
    de.indexed_params,
    de.data_params,
    de.run_partition_id
FROM {{ ref('seed_decoded_events') }} de
INNER JOIN {{ ref('stg_canonical_blocks') }} cb
    ON de.chain_id = cb.chain_id
   AND de.block_number = cb.block_number
WHERE de.event_name = 'Transfer'
  AND LOWER(de.contract_address) = '0x514910771af9ca656af840dff83e8264ecf986ca'
{% else %}
SELECT
    de.decoded_event_id,
    de.raw_log_id,
    de.chain_id,
    de.block_number,
    de.tx_hash,
    de.log_index,
    {{ lower_address('de.contract_address') }} AS token_address,
    de.indexed_params,
    de.data_params,
    de.run_partition_id
FROM {{ source('raw_external', 'decoded_events') }} de
INNER JOIN {{ ref('stg_canonical_blocks') }} cb
    ON de.chain_id = cb.chain_id
   AND de.block_number = cb.block_number
WHERE de.event_name = 'Transfer'
  AND LOWER(de.contract_address) = '0x514910771af9ca656af840dff83e8264ecf986ca'
{% endif %}
