-- Fails if count(failure_reason='unknown_topic') / total > threshold.
WITH counts AS (
    SELECT
        COUNT(*) AS total_failures,
        {{ countif("failure_reason = 'unknown_topic'") }} AS unknown_topic_count
    FROM {{ ref('int_decode_failures') }}
)
SELECT *
FROM counts
WHERE total_failures > 0
  AND unknown_topic_count * 100.0 / total_failures
      > {{ var('unknown_signature_threshold_pct') }}
