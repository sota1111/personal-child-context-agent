# Terraform + provider version constraints (SOT-2803).
# Pinned to the Google provider 6.x line, which supports google_cloud_run_v2_service
# startup/liveness probes and the named google_firestore_database used below.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}
