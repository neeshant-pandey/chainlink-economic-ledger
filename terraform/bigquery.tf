# BigQuery datasets for raw, staging, intermediate, marts, and analytics.
# dbt's profiles.yml binds to these dataset names by default.

resource "google_bigquery_dataset" "raw" {
  dataset_id    = "staking_raw"
  location      = var.gcp_region
  friendly_name = "Chainlink raw EVM artifacts"
  description   = "Externally-loaded parquet from GCS, populated by ingestion pipeline."

  default_table_expiration_ms = null
  labels                      = local.resource_labels
}

resource "google_bigquery_dataset" "staging" {
  dataset_id    = "staking_staging"
  location      = var.gcp_region
  friendly_name = "Chainlink staging models"
  labels        = local.resource_labels
}

resource "google_bigquery_dataset" "intermediate" {
  dataset_id    = "staking_intermediate"
  location      = var.gcp_region
  friendly_name = "Chainlink intermediate models"
  labels        = local.resource_labels
}

resource "google_bigquery_dataset" "marts" {
  dataset_id    = "staking_marts"
  location      = var.gcp_region
  friendly_name = "Chainlink marts (contract-enforced)"
  description   = "Headline marts: ledger_entries, staking_link_flows, etc."
  labels        = local.resource_labels
}

resource "google_bigquery_dataset" "analytics" {
  dataset_id    = "staking_analytics"
  location      = var.gcp_region
  friendly_name = "Chainlink tokenomics analytics"
  description   = "Per-question marts: APY, fee attribution, reserve growth."
  labels        = local.resource_labels
}
