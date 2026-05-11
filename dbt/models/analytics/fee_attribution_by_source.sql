{{ config(materialized='view') }}

-- Tokenomics question: where do PA fees come from (Chainlink service: VRF /
-- Functions / Data Streams / CCIP / other)?
--
-- Sources only from marts (per the analytics layering rule — never directly from
-- bigquery-public-data.crypto_ethereum.*).

{% if target.type == 'duckdb' %}
WITH service_map AS (
    SELECT '0x271682deb8c4e0901d1a1550ad2e64d568e69909' AS source_address, 'vrf' AS service
    UNION ALL SELECT '0x65dcc24f8ff9e51f10dcc7ed1e4e2a61e6e14bd6', 'functions'
    UNION ALL SELECT '0x80226fc0ee2b096224eeac085bb9a8cba1146f7d', 'ccip'
    UNION ALL SELECT '0x0000000000000000000000000000000000000001', 'data_streams'
)
{% else %}
WITH service_map AS (
    SELECT * FROM UNNEST([
        STRUCT('0x271682deb8c4e0901d1a1550ad2e64d568e69909' AS source_address, 'vrf' AS service),
        STRUCT('0x65dcc24f8ff9e51f10dcc7ed1e4e2a61e6e14bd6', 'functions'),
        STRUCT('0x80226fc0ee2b096224eeac085bb9a8cba1146f7d', 'ccip'),
        STRUCT('0x0000000000000000000000000000000000000001', 'data_streams')
    ])
)
{% endif %}
SELECT
    {{ date_from_seconds('cb.timestamp') }} AS snapshot_date,
    COALESCE(sm.service, 'other') AS service,
    SUBSTR(le.account, STRPOS(le.account, ':') + 1) AS source_address,
    SUM(le.amount_link) AS inflow_link,
    COUNT(DISTINCT le.tx_hash) AS tx_count
FROM {{ ref('ledger_entries') }} le
INNER JOIN {{ ref('stg_canonical_blocks') }} cb USING (block_number)
LEFT JOIN service_map sm
    ON LOWER(SUBSTR(le.account, STRPOS(le.account, ':') + 1)) = sm.source_address
WHERE le.direction = 'debit'
  AND le.account LIKE 'service_contract:%'
GROUP BY
    {{ date_from_seconds('cb.timestamp') }},
    COALESCE(sm.service, 'other'),
    SUBSTR(le.account, STRPOS(le.account, ':') + 1)
ORDER BY snapshot_date DESC, inflow_link DESC
