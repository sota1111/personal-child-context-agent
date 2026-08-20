# Cloud Run v2 service for the PCCA backend (SOT-2803).
# Mirrors scripts/deploy_cloudrun.sh: dedicated runtime SA, secrets from Secret
# Manager, non-secret config as env vars, /health startup + liveness probes, and the
# scale/concurrency knobs from SOT-2804.
#
# NOTE: the container image is built + pushed by Cloud Build (`gcloud run deploy
# --source .`). Terraform references an existing image (var.container_image) and does
# not build it, so `plan` stays clean when only the app code changes. ignore_changes
# on the image lets the deploy script roll new revisions without Terraform drift.
locals {
  # Non-secret runtime configuration (matches deploy_cloudrun.sh ENV_VARS).
  base_env = {
    APP_ENV                   = "production"
    LOG_LEVEL                 = var.log_level
    PCCA_PERSISTENCE          = "firestore"
    GOOGLE_GENAI_USE_VERTEXAI = "true"
    GOOGLE_CLOUD_PROJECT      = var.project_id
    GOOGLE_CLOUD_LOCATION     = var.vertex_location
    FIRESTORE_DATABASE        = var.firestore_database
  }

  # CORS_ORIGINS is only set when non-empty (deploy script does the same).
  plain_env = var.cors_origins == "" ? local.base_env : merge(local.base_env, {
    CORS_ORIGINS = var.cors_origins
  })
}

resource "google_cloud_run_v2_service" "backend" {
  project             = var.project_id
  name                = var.service_name
  location            = var.region
  deletion_protection = false

  template {
    service_account                  = google_service_account.runtime.email
    timeout                          = "${var.request_timeout_seconds}s"
    max_instance_request_concurrency = var.concurrency

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.container_image

      ports {
        container_port = var.container_port
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }

      # Non-secret env vars.
      dynamic "env" {
        for_each = local.plain_env
        content {
          name  = env.key
          value = env.value
        }
      }

      # Secret-backed env vars (value pulled from Secret Manager `latest`).
      dynamic "env" {
        for_each = var.secret_ids
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets[env.key].secret_id
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get {
          path = var.health_path
          port = var.container_port
        }
        initial_delay_seconds = 2
        period_seconds        = 5
        timeout_seconds       = 3
        failure_threshold     = 12
      }

      liveness_probe {
        http_get {
          path = var.health_path
          port = var.container_port
        }
        period_seconds    = 30
        timeout_seconds   = 3
        failure_threshold = 3
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.runtime_secret_accessor,
  ]

  lifecycle {
    # The deploy script rolls new image revisions out-of-band; don't fight it.
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }
}

# Public, unauthenticated access (matches --allow-unauthenticated).
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count = var.allow_unauthenticated ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
