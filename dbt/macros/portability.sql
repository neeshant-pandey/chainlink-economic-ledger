{# Portability macros: branch on `target.type` so the same SQL compiles for
   both BigQuery (production) and DuckDB (local). Plain target-type switch,
   not `adapter.dispatch` — the adapter set is just bigquery + duckdb. If a
   third backend is added, promote each macro to a `default__` / `bigquery__`
   / `duckdb__` triple under `adapter.dispatch(...)`. #}


{# `to_unix_timestamp(col)` -> a TIMESTAMP value from a unix-second integer. #}
{% macro ts_from_seconds(col) %}
    {%- if target.type == 'duckdb' -%}
        TO_TIMESTAMP({{ col }})
    {%- else -%}
        TIMESTAMP_SECONDS({{ col }})
    {%- endif -%}
{% endmacro %}


{# Cast a unix-second integer to DATE. #}
{% macro date_from_seconds(col) %}
    {%- if target.type == 'duckdb' -%}
        CAST(TO_TIMESTAMP({{ col }}) AS DATE)
    {%- else -%}
        DATE(TIMESTAMP_SECONDS({{ col }}))
    {%- endif -%}
{% endmacro %}


{# Truncate a DATE to its ISO Monday-week-start. #}
{% macro week_trunc_monday(date_col) %}
    {%- if target.type == 'duckdb' -%}
        DATE_TRUNC('week', {{ date_col }})
    {%- else -%}
        DATE_TRUNC({{ date_col }}, WEEK(MONDAY))
    {%- endif -%}
{% endmacro %}


{# `safe_divide(a, b)` — returns NULL when b is 0 (mirrors BQ's SAFE_DIVIDE). #}
{% macro safe_divide(a, b) %}
    {%- if target.type == 'duckdb' -%}
        ({{ a }}) / NULLIF({{ b }}, 0)
    {%- else -%}
        SAFE_DIVIDE({{ a }}, {{ b }})
    {%- endif -%}
{% endmacro %}


{# Conditional count: COUNTIF(predicate) on BQ, equivalent on DuckDB. #}
{% macro countif(predicate) %}
    {%- if target.type == 'duckdb' -%}
        COUNT(*) FILTER (WHERE {{ predicate }})
    {%- else -%}
        COUNTIF({{ predicate }})
    {%- endif -%}
{% endmacro %}


{# Length of an array column. #}
{% macro array_length_safe(col) %}
    {%- if target.type == 'duckdb' -%}
        len({{ col }})
    {%- else -%}
        ARRAY_LENGTH({{ col }})
    {%- endif -%}
{% endmacro %}


{# topic_at(arr, i) — 0-indexed access to an array column.
   BQ: arr[SAFE_OFFSET(i)] returns NULL on out-of-bounds.
   DuckDB: arr[i+1] returns NULL on out-of-bounds. #}
{% macro topic_at(col, i) %}
    {%- if target.type == 'duckdb' -%}
        {{ col }}[{{ i + 1 }}]
    {%- else -%}
        {{ col }}[SAFE_OFFSET({{ i }})]
    {%- endif -%}
{% endmacro %}


{# A NUMERIC column type alias. BQ has NUMERIC; DuckDB uses DECIMAL(38,0)
   to safely hold full uint256-scaled LINK amounts (worst case ~78 digits;
   we cap at 38 digits which still covers ~2.5e10 LINK at 1e18 wei). #}
{% macro link_numeric_type() %}
    {%- if target.type == 'duckdb' -%}
        DECIMAL(38,0)
    {%- else -%}
        NUMERIC
    {%- endif -%}
{% endmacro %}
