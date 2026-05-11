{{ config(materialized='view') }}

-- Tokenomics question: how much LINK is the PA Reserve accumulating per
-- week, broken down by source (PA fee inflow vs other)?
--
-- Sources only from marts (per the analytics layering rule — never directly from
-- bigquery-public-data.crypto_ethereum.*).
--
-- Sources used:
--   - ledger_entries: reservations of LINK landing at the PA reserves
--                     (account starts with 'pa_reserves:')
--   - stg_canonical_blocks: timestamp lookup for week bucketing
SELECT
    {{ week_trunc_monday(date_from_seconds('cb.timestamp')) }} AS week_start,
    CASE
        WHEN le.account LIKE 'pa_reserves:%' AND
             EXISTS (
                SELECT 1 FROM {{ ref('ledger_entries') }} other
                WHERE other.tx_hash = le.tx_hash
                  AND other.account LIKE 'pa_fee_aggregator:%'
             )
        THEN 'pa_fee_inflow'
        WHEN le.account LIKE 'pa_reserves:%'
        THEN 'other_inflow'
        ELSE 'unknown'
    END AS inflow_source,
    SUM(CASE WHEN le.direction = 'credit' THEN le.amount_link ELSE 0 END) AS link_inflow,
    COUNT(DISTINCT le.tx_hash) AS tx_count
FROM {{ ref('ledger_entries') }} le
INNER JOIN {{ ref('stg_canonical_blocks') }} cb USING (block_number)
WHERE le.account LIKE 'pa_reserves:%'
GROUP BY week_start, inflow_source
ORDER BY week_start DESC, inflow_source
