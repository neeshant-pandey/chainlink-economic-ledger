"""RPC fallback path.

Use only for: (1) freshness validation against BQ public dataset lag,
(2) recent-tip data not yet in BQ, (3) one-off integration checks. The primary
ingestion surface is `ingestion/bq/`.
"""
