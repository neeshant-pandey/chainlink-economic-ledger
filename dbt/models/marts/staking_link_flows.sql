{{ config(
    materialized='incremental',
    unique_key='event_id',
    incremental_strategy='merge',
    contract={'enforced': target.type != 'duckdb'}
) }}

-- Per-event wallet flow surface. One row per decoded_event_id. Filtered to
-- canonical (finalized) blocks only — reorged actions are excluded so
-- downstream analytics never see them.

SELECT
    a.decoded_event_id AS event_id,
    a.wallet,
    a.kind AS flow_type,
    a.amount_link,
    a.tx_hash,
    a.block_number,
    -- Map int_action_movement_recon.overall_status (ok/warn/fail) onto the
    -- per-edge enum (exact/partial/unmatched/...) so the schema constraint
    -- holds whether or not a tx-level row exists.
    -- Map upstream overall_status (ok/warn/fail) onto the per-edge enum.
    -- Unknown values fall through to 'unmatched' (worst-case), never 'exact'.
    CASE
        WHEN r.overall_status = 'ok'   THEN 'exact'
        WHEN r.overall_status = 'warn' THEN 'partial'
        WHEN r.overall_status = 'fail' THEN 'unmatched'
        ELSE 'unmatched'
    END AS reconciliation_status,
    a.run_partition_id
FROM {{ ref('int_economic_actions') }} a
INNER JOIN {{ ref('stg_canonical_blocks') }} cb
    ON cb.chain_id = a.chain_id
   AND cb.block_number = a.block_number
LEFT JOIN {{ ref('int_action_movement_recon') }} r
    ON a.tx_hash = r.tx_hash
WHERE a.wallet IS NOT NULL
{% if is_incremental() %}
  AND {{ incremental_block_predicate('a.block_number') }}
{% endif %}
