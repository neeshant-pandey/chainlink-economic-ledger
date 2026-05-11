# Limitations and next steps

This repository is designed as a reproducible local demo plus production-oriented architecture scaffold. The local path is the source of truth for what can be run without external services.

## Current limitations

- Airflow backfill, incremental, and reconciliation DAGs are planned adapters. The primary DAG imports cleanly, but production task bodies still need live scheduler/cloud wiring.
- Custom Airflow EVM operators are documented but not implemented; local tests exercise the underlying Python decode/reconciliation modules instead.
- Monitoring and source-manifest sinks require a production destination such as Cloud Monitoring, Slack/PagerDuty, BigQuery metadata tables, or another operational store.
- Databricks parity logic exists, but GCS-to-Delta materialization requires a live Databricks workspace.
- The local fixture demo covers selected real mainnet transactions; broad protocol coverage requires additional curated reference transactions.
- Some contract registry entries remain approximate or marked `TBD` pending independent verification.
- The APY analytics view is a reward-yield proxy, not a full time-weighted APY implementation.

## Practical next steps

1. Add more reference transactions for staking rewards, unstake flows, migration, slashing, and additional PA fee paths.
2. Wire the planned Airflow operators to the existing BigQuery/RPC extractors and dataset writers.
3. Add a source-manifest sink backed by BigQuery metadata tables.
4. Replace placeholder service-contract mappings with verified addresses.
5. Add true time-weighted principal snapshots for APY analytics.
