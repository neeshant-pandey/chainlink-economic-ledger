output "raw_dataset_id" {
  value       = google_bigquery_dataset.raw.dataset_id
  description = "BQ raw dataset id (Python ingestion writes here)."
}

output "marts_dataset_id" {
  value       = google_bigquery_dataset.marts.dataset_id
  description = "BQ marts dataset id (dbt writes contract-enforced marts here)."
}

output "raw_bucket_name" {
  value       = google_storage_bucket.raw.name
  description = "GCS bucket holding raw parquet."
}

output "ingestion_sa_email" {
  value       = google_service_account.ingestion.email
  description = "Service account used by the ingestion pipeline."
}
