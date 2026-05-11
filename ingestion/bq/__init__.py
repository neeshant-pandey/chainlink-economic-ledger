"""BigQuery-primary ingestion. Authoritative path.

Queries `bigquery-public-data.crypto_ethereum.*` (and L2 equivalents) for blocks,
transactions, logs, traces, token_transfers, and balances. The sibling
`ingestion/rpc/` package is fallback only — freshness validation and BQ-lag
backfill. New feature work goes here, not in `rpc/`.
"""
