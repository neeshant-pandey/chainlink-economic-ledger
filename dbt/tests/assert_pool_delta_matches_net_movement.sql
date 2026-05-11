-- Per pool snapshot: observed balance delta must equal the sum of canonical
-- token movements over the window. Tolerance = 0 LINK.
SELECT
    pool_address,
    block_number,
    observed_delta,
    net_movement_amount,
    observed_delta - net_movement_amount AS diff
FROM {{ ref('int_pool_balance_deltas') }}
WHERE observed_delta IS NOT NULL
  AND observed_delta != net_movement_amount
