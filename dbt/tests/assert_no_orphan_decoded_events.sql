-- Every decoded_event must have a matching raw_log row. Orphans indicate
-- ID-computation drift between Python and dbt.
SELECT de.decoded_event_id
FROM {{ ref('stg_staking_events') }} de
LEFT JOIN {{ ref('raw_logs') }} rl
    ON rl.chain_id = de.chain_id
   AND rl.block_number = de.block_number
   AND rl.tx_hash = de.tx_hash
   AND rl.log_index = de.log_index
WHERE rl.tx_hash IS NULL
