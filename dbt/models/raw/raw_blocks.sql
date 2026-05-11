{{ config(materialized='view') }}

-- Passthrough from the GCS-backed external table populated by the Python
-- block_fetcher. NO decoding or filtering here — those happen in staging/.
--
-- Local target (DuckDB): the seed CSV produced by `scripts/seed_to_local.py`
-- already carries the canonical block rows (chain_id, block_number,
-- block_hash, parent_hash, timestamp, ingested_at, run_partition_id).
{% if target.type == 'duckdb' %}
SELECT
    chain_id,
    block_number,
    block_hash,
    parent_hash,
    timestamp,
    ingested_at,
    run_partition_id
FROM {{ ref('seed_canonical_blocks') }}
{% else %}
SELECT * FROM {{ source('raw_external', 'raw_blocks') }}
{% endif %}
