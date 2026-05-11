# Root Terraform configuration. Splits resources into per-resource files
# (bigquery.tf, gcs.tf, service_account.tf) per the Terraform module layout file count.
#
# Backend: gcs (configured at apply time via -backend-config, NOT committed).
#
# Reviewer note: this is the IaC for the demo; not intended for production
# without further hardening (state locking, IAM least-privilege, audit logs).

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.gcp_project
  region  = var.gcp_region
}

# Project-level resource-bag locals — keeps individual files terse.
locals {
  resource_labels = {
    application = "chainlink-economic-ledger"
    owner       = "data-engineering"
    managed_by  = "terraform"
  }
}
