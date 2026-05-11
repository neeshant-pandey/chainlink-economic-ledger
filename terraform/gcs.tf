# GCS buckets for raw parquet storage and dbt artifact uploads.

resource "google_storage_bucket" "raw" {
  name          = "${var.gcp_project}-staking-raw"
  location      = var.gcp_region
  force_destroy = false

  uniform_bucket_level_access = true
  storage_class               = "STANDARD"

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action {
      type = "SetStorageClass"
      storage_class = "NEARLINE"
    }
    condition {
      age = 30
    }
  }

  labels = local.resource_labels
}

resource "google_storage_bucket" "dbt_artifacts" {
  name          = "${var.gcp_project}-dbt-artifacts"
  location      = var.gcp_region
  force_destroy = false

  uniform_bucket_level_access = true
  labels                      = local.resource_labels
}
