{# Deterministic surrogate key from a list of fields. Hex string (no separator
   leakage from concat); NULLs cast to empty string for stability across replays.
   - BigQuery: SHA256 returns BYTES; wrap in TO_HEX.
   - DuckDB:   SHA256 returns a hex VARCHAR directly. #}
{% macro surrogate_key(fields) %}
    {%- if target.type == 'duckdb' -%}
        SHA256(CONCAT(
            {%- for f in fields -%}
                COALESCE(CAST({{ f }} AS VARCHAR), '')
                {%- if not loop.last %}, '|', {% endif -%}
            {%- endfor -%}
        ))
    {%- else -%}
        TO_HEX(SHA256(CONCAT(
            {%- for f in fields -%}
                COALESCE(CAST({{ f }} AS STRING), '')
                {%- if not loop.last %}, '|', {% endif -%}
            {%- endfor -%}
        )))
    {%- endif -%}
{% endmacro %}
