{# Returns TRUE if `block_number_col` is below the project's finality
   watermark. Watermark = (latest finalized block tag) - finality_depth.
   The Python pipeline writes only finalized rows; this macro is a
   defense-in-depth filter. We model the watermark as
   "max raw_blocks - finality_depth".

   Local target (DuckDB) sources from the seed CSV, since the BQ source is
   unreachable. Both branches share the same shape — `MAX(block_number) -
   finality_depth`. #}
{% macro is_finalized(block_number_col) %}
    {%- if target.type == 'duckdb' -%}
    {{ block_number_col }} <= (
        SELECT COALESCE(MAX(block_number), 0) - {{ var('finality_depth', 64) }}
        FROM {{ ref('seed_canonical_blocks') }}
    )
    {%- else -%}
    {{ block_number_col }} <= (
        SELECT COALESCE(MAX(block_number), 0) - {{ var('finality_depth', 64) }}
        FROM {{ source('raw_external', 'raw_blocks') }}
    )
    {%- endif -%}
{% endmacro %}
