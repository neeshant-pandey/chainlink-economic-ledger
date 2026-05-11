{{ config(
    materialized='incremental',
    unique_key=['pool_address', 'snapshot_date'],
    incremental_strategy='merge',
    contract={'enforced': target.type != 'duckdb'}
) }}

-- Daily per-pool rollup: rewards distributed, slashes applied, end-of-day
-- balance.
SELECT
    a.contract_address AS pool_address,
    {{ date_from_seconds('cb.timestamp') }} AS snapshot_date,
    SUM(CASE WHEN a.kind = 'reward_accrued' THEN a.amount_link ELSE 0 END) AS rewards_distributed,
    SUM(CASE WHEN a.kind = 'slashed' THEN a.amount_link ELSE 0 END) AS slashes_applied,
    -- end-of-day balance approximated as max balance observed in the day
    COALESCE(
        (
            SELECT MAX(s.balance)
            FROM {{ ref('stg_balance_snapshots') }} s
            WHERE s.holder_address = a.contract_address
              AND s.token_address = '0x514910771af9ca656af840dff83e8264ecf986ca'
        ),
        0
    ) AS end_of_day_balance,
    MAX(a.run_partition_id) AS run_partition_id
FROM {{ ref('int_economic_actions') }} a
INNER JOIN {{ ref('stg_canonical_blocks') }} cb USING (block_number)
{% if is_incremental() %}
WHERE {{ incremental_block_predicate('a.block_number') }}
{% endif %}
GROUP BY a.contract_address, snapshot_date
