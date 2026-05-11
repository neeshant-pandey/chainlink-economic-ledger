{# Deterministic ID for a ledger entry. Mirrors `protocol.ledger_builder.compute_ledger_entry_id`. #}
{% macro ledger_entry_id(action_id_col, entry_index_col) %}
    {{ surrogate_key([action_id_col, entry_index_col]) }}
{% endmacro %}
