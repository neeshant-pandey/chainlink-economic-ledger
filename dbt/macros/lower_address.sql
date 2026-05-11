{# Lower-cased EVM address. Use everywhere addresses are compared/joined. #}
{% macro lower_address(col) %}
    LOWER({{ col }})
{% endmacro %}
