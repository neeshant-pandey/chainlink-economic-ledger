{{ config(materialized='view') }}

-- Canonical block view: only finalized blocks (per finality watermark) with
-- the latest observed block_hash if a reorg occurred. Promotion handled in
-- Python; this model just exposes the result.

WITH ranked AS (
    SELECT
        chain_id,
        block_number,
        block_hash,
        parent_hash,
        timestamp,
        run_partition_id,
        ROW_NUMBER() OVER (
            PARTITION BY chain_id, block_number
            ORDER BY ingested_at DESC
        ) AS rn
    FROM {{ ref('raw_blocks') }}
    WHERE {{ is_finalized('block_number') }}
)
SELECT chain_id, block_number, block_hash, parent_hash, timestamp, run_partition_id
FROM ranked
WHERE rn = 1
