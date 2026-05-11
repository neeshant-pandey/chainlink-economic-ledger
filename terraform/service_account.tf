# Service accounts: one for ingestion (BQ public dataset reads + GCS writes),
# one for dbt (BQ writes against private datasets).

resource "google_service_account" "ingestion" {
  account_id   = "ingestion"
  display_name = "Chainlink ingestion (BQ reads + GCS writes)"
}

resource "google_service_account" "dbt" {
  account_id   = "dbt-runner"
  display_name = "dbt runner (writes marts in private datasets)"
}

# Ingestion role bindings
resource "google_project_iam_member" "ingestion_bq_user" {
  project = var.gcp_project
  role    = "roles/bigquery.user"
  member  = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_storage_bucket_iam_member" "ingestion_writer" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.ingestion.email}"
}

# dbt role bindings
resource "google_project_iam_member" "dbt_data_editor" {
  project = var.gcp_project
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.dbt.email}"
}

resource "google_project_iam_member" "dbt_job_user" {
  project = var.gcp_project
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.dbt.email}"
}
