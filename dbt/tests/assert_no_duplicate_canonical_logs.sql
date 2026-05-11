-- Asserts no `(chain_id, block_number, tx_hash, log_index)` appears more
-- than once in raw_logs filtered to canonical blocks. Catches reorg-driven
-- double-ingestion.
SELECT
    rl.chain_id,
    rl.block_number,
    rl.tx_hash,
    rl.log_index,
    COUNT(*) AS occurrences
FROM {{ ref('raw_logs') }} rl
INNER JOIN {{ ref('stg_canonical_blocks') }} cb USING (chain_id, block_number)
GROUP BY rl.chain_id, rl.block_number, rl.tx_hash, rl.log_index
HAVING COUNT(*) > 1
