{# Deterministic ID for a trace call: `(tx_hash, trace_address[])`. Mirrors the
   Python `decoder.trace_decoder.compute_raw_trace_call_id`. #}
{% macro trace_call_id(tx_hash_col, trace_address_col) %}
    {{ surrogate_key([tx_hash_col, "ARRAY_TO_STRING(" ~ trace_address_col ~ ", ',')"]) }}
{% endmacro %}
