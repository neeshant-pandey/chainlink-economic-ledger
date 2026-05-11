{{ config(materialized='view') }}

-- Daily reward-yield proxy per pool. NOT a true time-weighted APY:
-- denominator is the daily change in principal, not the time-weighted average.
-- Treat as a rough daily check, not an APY-comparable series.
-- True TWAP-APY needs per-block principal snapshots from `lineage/balance_snapshots`.

WITH stake_changes AS (
    SELECT
        f.wallet,
        f.tx_hash,
        f.block_number,
        cb.timestamp,
        CASE
            WHEN f.flow_type = 'stake' THEN f.amount_link
            WHEN f.flow_type = 'unstake_finalized' THEN -f.amount_link
            ELSE 0
        END AS principal_delta,
        f.run_partition_id
    FROM {{ ref('staking_link_flows') }} f
    INNER JOIN {{ ref('stg_canonical_blocks') }} cb USING (block_number)
    WHERE f.flow_type IN ('stake', 'unstake_finalized')
),
rewards AS (
    SELECT
        f.wallet,
        cb.timestamp,
        f.amount_link,
        f.run_partition_id
    FROM {{ ref('staking_link_flows') }} f
    INNER JOIN {{ ref('stg_canonical_blocks') }} cb USING (block_number)
    WHERE f.flow_type = 'reward_claimed'
),
agg AS (
    SELECT
        {{ date_from_seconds('c.timestamp') }} AS snapshot_date,
        SUM(CASE WHEN s.principal_delta IS NOT NULL THEN s.principal_delta ELSE 0 END) AS net_principal_delta,
        SUM(CASE WHEN r.amount_link IS NOT NULL THEN r.amount_link ELSE 0 END) AS rewards_distributed
    FROM {{ ref('stg_canonical_blocks') }} c
    LEFT JOIN stake_changes s ON s.timestamp = c.timestamp
    LEFT JOIN rewards r ON r.timestamp = c.timestamp
    GROUP BY snapshot_date
)
SELECT
    snapshot_date,
    net_principal_delta,
    rewards_distributed,
    {{ safe_divide(
        "rewards_distributed * 31536000",
        "NULLIF(net_principal_delta, 0)"
    ) }} AS reward_yield_proxy_annualized
FROM agg
ORDER BY snapshot_date DESC
