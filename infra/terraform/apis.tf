# Google APIs the PCCA backend depends on (SOT-2803).
# Enabling these is idempotent; disable_on_destroy=false so a `terraform destroy`
# of this stack never turns APIs off for the whole project.
locals {
  required_apis = [
    "run.googleapis.com",              # Cloud Run
    "firestore.googleapis.com",        # Firestore (named db `pcca`)
    "secretmanager.googleapis.com",    # Secret Manager
    "aiplatform.googleapis.com",       # Vertex AI (Gemini)
    "iam.googleapis.com",              # service accounts / IAM
    "cloudbuild.googleapis.com",       # `gcloud run deploy --source .` builds
    "artifactregistry.googleapis.com", # image storage for Cloud Build
    "cloudresourcemanager.googleapis.com",
    "monitoring.googleapis.com", # Cloud Monitoring alert policies
  ]
}

resource "google_project_service" "required" {
  for_each = toset(local.required_apis)

  project = var.project_id
  service = each.value

  disable_on_destroy         = false
  disable_dependent_services = false
}
