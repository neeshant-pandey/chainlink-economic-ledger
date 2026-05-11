{{ config(materialized='view') }}

-- Shadow tip blocks — recent, not-yet-finalized blocks. Visibility-only;
-- marts never source from this view.

SELECT
    chain_id,
    block_number,
    block_hash,
    parent_hash,
    timestamp,
    run_partition_id
FROM {{ ref('raw_blocks') }}
WHERE NOT ({{ is_finalized('block_number') }})
