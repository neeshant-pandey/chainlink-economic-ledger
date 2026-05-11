# Databricks notebook source
# MAGIC %md
# MAGIC # GCS parquet → Delta
# MAGIC
# MAGIC Reads the same canonical parquet that BigQuery loads from. Materializes Delta
# MAGIC tables that mirror the dbt mart schema 1:1 — so `parity_check` can compare
# MAGIC by stable entity ID and full-row hash.
# MAGIC
# MAGIC Tables produced (per `comparison_window_days` window):
# MAGIC   - `delta.staking.ledger_entries`
# MAGIC   - `delta.staking.staking_link_flows`
# MAGIC   - `delta.staking.wallet_economics`
# MAGIC   - `delta.staking.pool_economics`
# MAGIC   - `delta.staking.reconciliation_status`

# COMMAND ----------

# TODO:
# 1. Read params: comparison_window_days
# 2. Resolve GCS paths from comparison window (read same partitions BigQuery loaded)
# 3. spark.read.parquet(...) for each mart
# 4. Apply same normalization as `parity_check`:
#       - LOWER(addresses)
#       - amounts as DECIMAL(38,0); never FLOAT
#       - timestamps as UTC ISO ms
# 5. Write to Delta with `mode='overwrite'` partitioned by snapshot_date (where applicable)

raise NotImplementedError(
    "Planned Databricks adapter: materialize GCS parquet into Delta tables before "
    "running the parity notebook in a live workspace."
)
