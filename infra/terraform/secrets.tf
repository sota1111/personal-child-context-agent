# Secret Manager secret CONTAINERS only (SOT-2803).
# The secret *values* are provisioned out-of-band (gcloud / console) and are never
# stored in Terraform config or state — no google_secret_manager_secret_version here.
# `lifecycle.ignore_changes` on replication keeps automatic replication stable across
# provider versions after import.
resource "google_secret_manager_secret" "secrets" {
  for_each = var.secret_ids

  project   = var.project_id
  secret_id = each.value

  replication {
    auto {}
  }
}
