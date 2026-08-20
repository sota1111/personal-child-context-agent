# Input variables for the PCCA infrastructure (SOT-2803).
# Defaults mirror the manually-provisioned production infra so `terraform plan`
# matches the existing resources after import. Secret *values* are never variables
# here — they are provisioned out-of-band (see secrets.tf / README).

variable "project_id" {
  description = "GCP project id hosting the PCCA backend."
  type        = string
  default     = "gen-lang-client-0243034020"
}

variable "region" {
  description = "Region for Cloud Run and Firestore."
  type        = string
  default     = "asia-northeast1"
}

variable "vertex_location" {
  description = "Vertex AI location (GOOGLE_CLOUD_LOCATION) the runtime uses for Gemini."
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Cloud Run service name (matches scripts/deploy_cloudrun.sh)."
  type        = string
  default     = "personal-child-context-agent-backend"
}

variable "container_image" {
  description = <<-EOT
    Fully-qualified container image the Cloud Run service runs. The image itself is
    built and pushed by Cloud Build (`gcloud run deploy --source .` / the Dockerfile);
    Terraform only references an existing tag/digest and does not build it. Point this
    at the current live revision's image when importing so `plan` is clean.
  EOT
  type        = string
  default     = "gcr.io/gen-lang-client-0243034020/personal-child-context-agent-backend:latest"
}

variable "firestore_database" {
  description = "Named Firestore database id used by the backend (FIRESTORE_DATABASE)."
  type        = string
  default     = "pcca"
}

variable "firestore_location" {
  description = "Firestore location id. Defaults to the deployment region."
  type        = string
  default     = "asia-northeast1"
}

variable "runtime_service_account_id" {
  description = "Account id (local part) for the Cloud Run runtime service account."
  type        = string
  default     = "pcca-backend-runtime"
}

variable "secret_ids" {
  description = <<-EOT
    Secret Manager secret ids the service mounts as env vars. Keys are the container
    env var names; values are the Secret Manager secret ids. Values/versions are NOT
    managed here — only the secret containers and IAM. See README for out-of-band value setup.
  EOT
  type        = map(string)
  default = {
    AUTH_SECRET         = "pcca-auth-secret"
    ALLOWED_USER_EMAILS = "pcca-allowed-emails"
    FIREBASE_API_KEY    = "pcca-firebase-api-key"
  }
}

variable "allow_unauthenticated" {
  description = "Grant run.invoker to allUsers (public service, matches --allow-unauthenticated)."
  type        = bool
  default     = true
}

# --- Scale + concurrency (mirrors SOT-2804 deploy defaults) ------------------
variable "min_instances" {
  description = "Minimum Cloud Run instances (0 = scale to zero)."
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum Cloud Run instances (cost / fan-out guard)."
  type        = number
  default     = 4
}

variable "concurrency" {
  description = "Max concurrent requests per instance."
  type        = number
  default     = 80
}

variable "cpu" {
  description = "CPU allocation per instance."
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Memory allocation per instance."
  type        = string
  default     = "512Mi"
}

variable "request_timeout_seconds" {
  description = "Request timeout in seconds."
  type        = number
  default     = 300
}

variable "container_port" {
  description = "Container port the backend binds ($PORT)."
  type        = number
  default     = 8080
}

variable "health_path" {
  description = "Unauthenticated HTTP path used by the startup + liveness probes."
  type        = string
  default     = "/health"
}

variable "log_level" {
  description = "Application log level (LOG_LEVEL)."
  type        = string
  default     = "INFO"
}

variable "cors_origins" {
  description = "Optional CORS_ORIGINS value; empty string omits the env var."
  type        = string
  default     = ""
}
