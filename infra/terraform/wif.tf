# Workload Identity Federation for keyless GitHub Actions deploys (SOT-2802).
#
# Lets the `.github/workflows/deploy-cloudrun.yml` job mint short-lived GCP
# credentials via the GitHub OIDC token — no service-account JSON key is ever
# created, downloaded, or stored in the repository. The deploy SA below is what
# GitHub Actions impersonates to build/push the image and deploy Cloud Run.

# Dedicated deploy service account (distinct from the least-privilege runtime SA
# in service_account.tf). google_project_iam_member is non-authoritative: it manages
# only these specific bindings and never strips other members.
resource "google_service_account" "deploy" {
  project      = var.project_id
  account_id   = var.deploy_service_account_id
  display_name = "GitHub Actions deployer (PCCA)"
  description  = "Keyless (WIF) deploy identity for ${var.service_name} — SOT-2802."

  depends_on = [google_project_service.required]
}

# Roles the deploy SA needs to build/push images and deploy the Cloud Run service.
locals {
  deploy_sa_roles = [
    "roles/run.admin",                # deploy Cloud Run revisions + manage traffic
    "roles/artifactregistry.writer",  # push the backend image
    "roles/iam.serviceAccountUser",   # actAs the runtime SA on deploy
    "roles/cloudbuild.builds.editor", # optional source builds
    "roles/storage.admin",            # Artifact Registry / build staging buckets
  ]
}

resource "google_project_iam_member" "deploy" {
  for_each = toset(local.deploy_sa_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deploy.email}"
}

# The deploy SA must be able to actAs the runtime SA to deploy a service that RUNS
# as the runtime SA (otherwise: PERMISSION_DENIED iam.serviceaccounts.actAs).
resource "google_service_account_iam_member" "deploy_act_as_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deploy.email}"
}

# --- Workload Identity Federation pool + GitHub OIDC provider ----------------
resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = var.wif_pool_id
  display_name              = "GitHub Actions"
  description               = "OIDC pool for GitHub Actions deploys (PCCA, SOT-2802)"

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = var.wif_provider_id
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
  }

  # Restrict token exchange to this repository only — no other repo can assume the
  # deploy SA even if it obtains a GitHub OIDC token.
  attribute_condition = "assertion.repository == \"${var.github_repository}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Allow the GitHub repo (via the pool) to impersonate the deploy SA.
resource "google_service_account_iam_member" "deploy_wif" {
  service_account_id = google_service_account.deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}
