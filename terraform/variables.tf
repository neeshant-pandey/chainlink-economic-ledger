variable "gcp_project" {
  type        = string
  description = "GCP project that owns BQ jobs (NOT the dataset's project)."
}

variable "gcp_region" {
  type        = string
  default     = "US"
  description = "Required to be 'US' for bigquery-public-data.crypto_ethereum reads."
}

variable "environment" {
  type        = string
  default     = "dev"
  description = "Environment tag: dev | staging | prod."
}
