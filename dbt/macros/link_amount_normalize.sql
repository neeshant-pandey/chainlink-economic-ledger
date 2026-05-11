{# LINK amounts are stored as raw uint256 (1e18). DO NOT cast to FLOAT64 for
   accounting columns — use NUMERIC. This macro is for display columns only. #}
{% macro link_amount_normalize(col) %}
    CAST({{ col }} AS NUMERIC) / POW(10, 18)
{% endmacro %}
