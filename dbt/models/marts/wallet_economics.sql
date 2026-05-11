{{ config(
    materialized='incremental',
    unique_key=['wallet', 'snapshot_date'],
    incremental_strategy='merge',
    contract={'enforced': target.type != 'duckdb'}
) }}

-- Daily per-wallet rollup: total staked, claimed, slashed, net flow.
SELECT
    f.wallet,
    {{ date_from_seconds('cb.timestamp') }} AS snapshot_date,
    SUM(CASE WHEN f.flow_type = 'stake' THEN f.amount_link ELSE 0 END) AS total_staked,
    SUM(CASE WHEN f.flow_type = 'reward_claimed' THEN f.amount_link ELSE 0 END) AS total_claimed,
    SUM(CASE WHEN f.flow_type = 'slashed' THEN f.amount_link ELSE 0 END) AS total_slashed,
    SUM(
        CASE
            WHEN f.flow_type IN ('stake') THEN -f.amount_link
            WHEN f.flow_type IN ('unstake_finalized', 'reward_claimed') THEN f.amount_link
            ELSE 0
        END
    ) AS net_flow,
    MAX(f.run_partition_id) AS run_partition_id
FROM {{ ref('staking_link_flows') }} f
INNER JOIN {{ ref('stg_canonical_blocks') }} cb USING (block_number)
{% if is_incremental() %}
WHERE {{ incremental_block_predicate('f.block_number') }}
{% endif %}
GROUP BY f.wallet, snapshot_date
