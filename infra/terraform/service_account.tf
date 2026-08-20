# Runtime service account for the Cloud Run backend + its IAM (SOT-2803).
# The service runs as a dedicated least-privilege SA rather than the default
# compute/appspot account. Roles granted match what the backend actually uses:
#   * secretmanager.secretAccessor — read the mounted secrets (bound per-secret)
#   * datastore.user               — read/write the named Firestore db `pcca`
#   * aiplatform.user              — call Gemini via Vertex AI
resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = var.runtime_service_account_id
  display_name = "PCCA Cloud Run backend runtime"
  description  = "Runtime identity for ${var.service_name} (managed by Terraform, SOT-2803)."
}

# Firestore read/write.
resource "google_project_iam_member" "runtime_datastore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# Vertex AI (Gemini) access.
resource "google_project_iam_member" "runtime_aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# Secret access, scoped to only the secrets this service mounts (least privilege).
resource "google_secret_manager_secret_iam_member" "runtime_secret_accessor" {
  for_each = google_secret_manager_secret.secrets

  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}
