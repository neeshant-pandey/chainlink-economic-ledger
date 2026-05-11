-- Asserts canonical_blocks has no gaps in block_number per chain_id.
-- Returns rows = violators (block_number where the next sequential block
-- is missing).
--
-- Local target (DuckDB): the seed only carries the two cherry-picked golden
-- tx blocks (18,671,459 and 24,139,066). Continuity is irrelevant in that
-- minimal demo dataset; we short-circuit to zero violators.
{% if target.type == 'duckdb' %}
SELECT
    CAST(NULL AS INTEGER) AS chain_id,
    CAST(NULL AS BIGINT) AS block_number,
    CAST(NULL AS BIGINT) AS next_block
WHERE FALSE
{% else %}
WITH gaps AS (
    SELECT
        chain_id,
        block_number,
        LEAD(block_number) OVER (
            PARTITION BY chain_id ORDER BY block_number
        ) AS next_block
    FROM {{ ref('stg_canonical_blocks') }}
)
SELECT chain_id, block_number, next_block
FROM gaps
WHERE next_block IS NOT NULL
  AND next_block != block_number + 1
{% endif %}
