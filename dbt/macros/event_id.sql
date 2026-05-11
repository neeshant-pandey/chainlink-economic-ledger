{# Canonical event ID from `(chain_id, block_number, tx_hash, log_index)`.
   Mirrors `decoder.event_decoder.compute_raw_log_id`. Use to join staging
   models back to raw_logs. #}
{% macro event_id(chain_id_col, block_number_col, tx_hash_col, log_index_col) %}
    {{ surrogate_key([chain_id_col, block_number_col, tx_hash_col, log_index_col]) }}
{% endmacro %}
