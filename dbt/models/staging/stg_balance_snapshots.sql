{{ config(materialized='view') }}

-- Pool/wallet balanceOf snapshots. Used by int_pool_balance_deltas to
-- cross-check Python movement totals against on-chain truth.
SELECT
    chain_id,
    block_number,
    {{ lower_address('token_address') }} AS token_address,
    {{ lower_address('holder_address') }} AS holder_address,
    balance,
    run_partition_id
FROM {{ ref('raw_balance_snapshots') }}
