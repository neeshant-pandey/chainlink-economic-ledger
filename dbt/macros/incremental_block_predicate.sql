{# Predicate for `is_incremental()` blocks. Filters to blocks newer than the
   highest already-materialized block, MINUS a small overlap window (default 50)
   to safely handle late-arriving rows (e.g., a slow trace ingestion catching up).

   DuckDB caveat: aggregate subqueries inside WHERE are rejected by the binder
   ("WHERE clause cannot contain aggregates"). We pre-compute the watermark
   inline as a constant the binder accepts via a `(SELECT COALESCE(MAX(...), 0) - overlap)`
   that DuckDB rewrites internally. The unwrapped form below works on both BQ
   and DuckDB. #}
{% macro incremental_block_predicate(block_col='block_number', overlap=50) %}
    {%- if target.type == 'duckdb' -%}
    {{ block_col }} > COALESCE(
        (SELECT MAX(block_number) FROM {{ this }}), 0
    ) - {{ overlap }}
    {%- else -%}
    {{ block_col }} > (
        SELECT COALESCE(MAX(block_number), 0) - {{ overlap }} FROM {{ this }}
    )
    {%- endif -%}
{% endmacro %}
