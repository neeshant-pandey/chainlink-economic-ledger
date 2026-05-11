{{ config(materialized='view') }}

-- Pre-decoded staking events. The Python `decoder.event_decoder` writes
-- decoded_events parquet → BQ external table. This model is a passthrough
-- with canonical-block filtering only (NO decoding logic — the Python-authoritative decoding invariant).
--
-- this model must NOT contain JSON_EXTRACT(topics) or
-- SUBSTR(data, ...) of raw bytes. Decoding is authoritative in Python.
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
    {{ lower_address('de.contract_address') }} AS contract_address,
    de.event_name,
    de.event_signature,
    de.indexed_params,
    de.data_params,
    de.run_partition_id
FROM {{ ref('seed_decoded_events') }} de
INNER JOIN {{ ref('stg_canonical_blocks') }} cb
    ON de.chain_id = cb.chain_id
   AND de.block_number = cb.block_number
WHERE de.event_name IN (
    'Staked',
    'UnstakeRequested',
    'Unstaked',
    'RewardClaimed',
    'RewardAdded',
    'Slashed',
    'Migrated',
    'PoolConfigChanged'
)
{% else %}
SELECT
    de.decoded_event_id,
    de.raw_log_id,
    de.chain_id,
    de.block_number,
    de.tx_hash,
    de.log_index,
    {{ lower_address('de.contract_address') }} AS contract_address,
    de.event_name,
    de.event_signature,
    de.indexed_params,
    de.data_params,
    de.run_partition_id
FROM {{ source('raw_external', 'decoded_events') }} de
INNER JOIN {{ ref('stg_canonical_blocks') }} cb
    ON de.chain_id = cb.chain_id
   AND de.block_number = cb.block_number
WHERE de.event_name IN (
    'Staked',
    'UnstakeRequested',
    'Unstaked',
    'RewardClaimed',
    'RewardAdded',
    'Slashed',
    'Migrated',
    'PoolConfigChanged'
)
{% endif %}
