{{ config(
    materialized='incremental',
    unique_key='partition_id',
    incremental_strategy='merge',
    contract={'enforced': target.type != 'duckdb'}
) }}

-- Partition-level reconciliation traffic light. Powered by Python-produced
-- partition_reconciliation parquet.
--
-- Canonical-block filter: a partition is exposed only if its
-- block_range_end has a corresponding canonical (finalized) block. Partitions
-- whose tip block reorged out are excluded automatically so consumers never
-- see traffic-light state for reorged ranges.
--
-- Local target (DuckDB): no Python-emitted partition_reconciliation rows
-- exist for the golden fixtures. We synthesize a single partition row from
-- the live edge data so the mart is non-empty and the schema is exercised.

{% if target.type == 'duckdb' %}
WITH edges AS (
    SELECT
        chain_id,
        MIN(block_number) AS block_range_start,
        MAX(block_number) AS block_range_end,
        COUNT(*) AS edge_count,
        {{ countif("status = 'exact'") }} AS exact_count,
        {{ countif("status = 'partial'") }} AS partial_count,
        {{ countif("status = 'unmatched'") }} AS unmatched_count,
        {{ countif("status = 'not_expected'") }} AS not_expected_count,
        {{ countif("status = 'unexpected'") }} AS unexpected_count,
        {{ countif("status = 'ambiguous'") }} AS ambiguous_count,
        MAX(run_partition_id) AS run_partition_id
    FROM {{ ref('stg_action_movement_edges') }}
    GROUP BY chain_id
)
SELECT
    {{ surrogate_key(["edges.chain_id", "edges.block_range_start", "edges.block_range_end"]) }} AS partition_id,
    edges.chain_id,
    edges.block_range_start,
    edges.block_range_end,
    CAST(
        (edges.exact_count + edges.not_expected_count) * 1.0 /
        NULLIF(edges.edge_count, 0)
    AS DOUBLE) AS pass_rate,
    CONCAT(
        '{"exact":', CAST(edges.exact_count AS VARCHAR),
        ',"partial":', CAST(edges.partial_count AS VARCHAR),
        ',"unmatched":', CAST(edges.unmatched_count AS VARCHAR),
        ',"not_expected":', CAST(edges.not_expected_count AS VARCHAR),
        ',"unexpected":', CAST(edges.unexpected_count AS VARCHAR),
        ',"ambiguous":', CAST(edges.ambiguous_count AS VARCHAR),
        '}'
    ) AS counts_by_status,
    edges.run_partition_id
FROM edges
INNER JOIN {{ ref('stg_canonical_blocks') }} cb
    ON cb.chain_id = edges.chain_id
   AND cb.block_number = edges.block_range_end
{% else %}
SELECT
    pr.partition_id,
    pr.chain_id,
    pr.block_range_start,
    pr.block_range_end,
    pr.pass_rate,
    pr.counts_by_status,
    pr.run_partition_id
FROM {{ source('raw_external', 'partition_reconciliation') }} pr
INNER JOIN {{ ref('stg_canonical_blocks') }} cb
    ON cb.chain_id = pr.chain_id
   AND cb.block_number = pr.block_range_end
{% endif %}
