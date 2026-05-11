{{ config(materialized='view') }}

-- Tokenomics question: are reward outflows sustainable vs reserve growth?
-- A simple ratio per snapshot date.
--
-- Sources only from marts (per the analytics layering rule).
WITH rewards AS (
    SELECT
        {{ date_from_seconds('cb.timestamp') }} AS snapshot_date,
        SUM(le.amount_link) AS rewards_distributed
    FROM {{ ref('ledger_entries') }} le
    INNER JOIN {{ ref('stg_canonical_blocks') }} cb USING (block_number)
    WHERE le.direction = 'credit' AND le.account LIKE '%:rewards'
    GROUP BY snapshot_date
),
reserves AS (
    SELECT
        {{ date_from_seconds('cb.timestamp') }} AS snapshot_date,
        SUM(le.amount_link) AS reserves_inflow
    FROM {{ ref('ledger_entries') }} le
    INNER JOIN {{ ref('stg_canonical_blocks') }} cb USING (block_number)
    WHERE le.direction = 'credit' AND le.account LIKE 'pa_reserves:%'
    GROUP BY snapshot_date
)
SELECT
    COALESCE(r.snapshot_date, v.snapshot_date) AS snapshot_date,
    COALESCE(r.rewards_distributed, 0) AS rewards_distributed,
    COALESCE(v.reserves_inflow, 0) AS reserves_inflow,
    {{ safe_divide(
        "COALESCE(r.rewards_distributed, 0)",
        "NULLIF(COALESCE(v.reserves_inflow, 0), 0)"
    ) }} AS rewards_to_reserves_ratio
FROM rewards r
FULL OUTER JOIN reserves v USING (snapshot_date)
ORDER BY snapshot_date DESC
