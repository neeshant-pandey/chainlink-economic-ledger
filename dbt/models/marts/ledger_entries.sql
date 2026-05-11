{{ config(
    materialized='incremental',
    unique_key='entry_id',
    incremental_strategy='merge',
    contract={'enforced': target.type != 'duckdb'}
) }}

-- Headline mart #1: double-entry economic ledger.
-- Source of truth for all wallet/pool LINK accounting.
--
-- Invariant (enforced by dbt/tests/assert_ledger_balanced_per_tx.sql):
--   For every (chain_id, tx_hash):
--     SUM(amount_link) WHERE direction='debit' == SUM(amount_link) WHERE direction='credit'
--
-- Note: run_partition_id is a column (lineage) but NOT in unique_key.
--
-- Local target (DuckDB): seeds carry the same LedgerEntry rows from both
-- staking + PA semantic layers.

{% if target.type == 'duckdb' %}
SELECT
    le.entry_id,
    le.action_id,
    le.entry_index,
    le.account,
    le.direction,
    le.amount_link,
    le.chain_id,
    le.block_number,
    le.tx_hash,
    le.run_partition_id
FROM {{ ref('seed_ledger_entries') }} le
INNER JOIN {{ ref('stg_canonical_blocks') }} cb USING (chain_id, block_number)
{% if is_incremental() %}
WHERE {{ incremental_block_predicate('le.block_number') }}
{% endif %}
{% else %}
SELECT
    entry_id,
    action_id,
    entry_index,
    account,
    direction,
    amount_link,
    chain_id,
    block_number,
    tx_hash,
    run_partition_id
FROM {{ source('raw_external', 'ledger_entries') }} le
INNER JOIN {{ ref('stg_canonical_blocks') }} cb USING (chain_id, block_number)
{% if is_incremental() %}
WHERE {{ incremental_block_predicate('le.block_number') }}
{% endif %}
{% endif %}
