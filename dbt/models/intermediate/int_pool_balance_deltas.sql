{{ config(
    materialized='incremental',
    unique_key=['pool_address', 'block_number'],
    incremental_strategy='merge'
) }}

-- Per-pool LINK balance delta between consecutive snapshots, plus the net
-- token movement implied by canonical movements over the same range. Used
-- by `assert_pool_delta_matches_net_movement`.
WITH balance_diffs AS (
    SELECT
        s.holder_address AS pool_address,
        s.block_number,
        s.balance,
        s.balance - LAG(s.balance) OVER (
            PARTITION BY s.holder_address ORDER BY s.block_number
        ) AS observed_delta,
        LAG(s.block_number) OVER (
            PARTITION BY s.holder_address ORDER BY s.block_number
        ) AS prev_block,
        s.run_partition_id
    FROM {{ ref('stg_balance_snapshots') }} s
    WHERE s.token_address = '0x514910771af9ca656af840dff83e8264ecf986ca'
),
net_movements AS (
    SELECT
        addr AS pool_address,
        block_number_end AS block_number,
        SUM(net_amount) AS net_amount
    FROM (
        SELECT to_addr AS addr,
               block_number AS block_number_end,
               amount AS net_amount
        FROM {{ ref('int_token_movements') }}
        UNION ALL
        SELECT from_addr AS addr,
               block_number AS block_number_end,
               -amount AS net_amount
        FROM {{ ref('int_token_movements') }}
    )
    GROUP BY addr, block_number_end
)
SELECT
    bd.pool_address,
    bd.block_number,
    bd.balance,
    bd.observed_delta,
    bd.prev_block,
    COALESCE(nm.net_amount, 0) AS net_movement_amount,
    bd.run_partition_id
FROM balance_diffs bd
LEFT JOIN net_movements nm
    ON bd.pool_address = nm.pool_address
   AND bd.block_number = nm.block_number
WHERE bd.prev_block IS NOT NULL
{% if is_incremental() %}
  AND {{ incremental_block_predicate('bd.block_number') }}
{% endif %}
