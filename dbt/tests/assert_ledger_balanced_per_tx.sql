-- Per-tx invariant: SUM(debits) == SUM(credits).
-- Returns rows where the difference is non-zero — these are violators.
-- Required by the double-entry invariant.
SELECT
    chain_id,
    tx_hash,
    SUM(CASE WHEN direction = 'debit'  THEN amount_link ELSE 0 END) AS debits,
    SUM(CASE WHEN direction = 'credit' THEN amount_link ELSE 0 END) AS credits,
    SUM(CASE WHEN direction = 'debit'  THEN amount_link ELSE -amount_link END) AS delta
FROM {{ ref('ledger_entries') }}
GROUP BY chain_id, tx_hash
HAVING delta != 0
