# Useful outputs (SOT-2803). None expose secret values.
output "service_uri" {
  description = "Public URL of the Cloud Run backend service."
  value       = google_cloud_run_v2_service.backend.uri
}

output "service_name" {
  description = "Cloud Run service name."
  value       = google_cloud_run_v2_service.backend.name
}

output "runtime_service_account_email" {
  description = "Email of the runtime service account the service runs as."
  value       = google_service_account.runtime.email
}

output "firestore_database" {
  description = "Named Firestore database id."
  value       = google_firestore_database.pcca.name
}

output "secret_ids" {
  description = "Secret Manager secret ids managed by this stack (values not included)."
  value       = [for s in google_secret_manager_secret.secrets : s.secret_id]
}

# --- Keyless CI/CD deploy outputs (SOT-2802) ---------------------------------
# Copy these into the GitHub repo secrets consumed by deploy-cloudrun.yml.
output "deploy_service_account_email" {
  description = "GitHub Actions deploy SA email (set as GitHub secret GCP_SERVICE_ACCOUNT)."
  value       = google_service_account.deploy.email
}

output "workload_identity_provider" {
  description = "Full WIF provider resource name (set as GitHub secret GCP_WORKLOAD_IDENTITY_PROVIDER)."
  value       = google_iam_workload_identity_pool_provider.github.name
}
