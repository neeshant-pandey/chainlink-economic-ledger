{# Inner-joins the calling model against `stg_canonical_blocks` so only finalized,
   reorg-resolved blocks contribute. Use in any staging/intermediate model that
   reads from a raw external table. #}
{% macro canonical_block_filter(alias='r') %}
    INNER JOIN {{ ref('stg_canonical_blocks') }} cb
        ON {{ alias }}.chain_id = cb.chain_id
       AND {{ alias }}.block_number = cb.block_number
       AND {{ alias }}.block_hash = cb.block_hash
{% endmacro %}
