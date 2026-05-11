{{ config(materialized='view') }}

-- Reconciliation edges produced by Python `economic_reconciler`. dbt does NOT
-- compute these — it only exposes them for downstream aggregation/testing.
--
-- Local target (DuckDB): seeds carry the same edge rows.

{% if target.type == 'duckdb' %}
SELECT
    edge_id,
    action_id,
    movement_id,
    allocated_amount,
    status,
    method,
    reason,
    chain_id,
    block_number,
    tx_hash,
    run_partition_id
FROM {{ ref('seed_action_movement_edges') }}
{% else %}
SELECT
    edge_id,
    action_id,
    movement_id,
    allocated_amount,
    status,
    method,
    reason,
    chain_id,
    block_number,
    tx_hash,
    run_partition_id
FROM {{ source('raw_external', 'action_movement_edges') }}
{% endif %}
