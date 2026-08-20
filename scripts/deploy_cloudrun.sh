#!/usr/bin/env bash
set -euo pipefail

# Cloud Run deploy for the Personal Child Context Agent backend (SOT-2794).
# Follows the おたよりナビ (toddler-private-rag) structure: a single FastAPI backend
# service, secrets from Secret Manager, non-secret config from env vars.
#
# Usage:
#   GCP_PROJECT_ID=sota-app-hub bash scripts/deploy_cloudrun.sh
#
# Prerequisites (one-time):
#   * gcloud auth login && gcloud config set project sota-app-hub
#   * Firestore provisioned in the same project (SOT-2739) — co-located to avoid
#     cross-project IAM.
#   * Secret Manager secrets created (see SECRETS below).
#   * The Cloud Run service account may read those secrets and use Firestore + Vertex AI.

PROJECT_ID="${GCP_PROJECT_ID:?GCP_PROJECT_ID is required (e.g. sota-app-hub)}"
REGION="${REGION:-asia-northeast1}"
SERVICE="${SERVICE:-personal-child-context-agent-backend}"
VERTEX_LOCATION="${VERTEX_LOCATION:-us-central1}"

# --- Scale + concurrency (SOT-2804) -----------------------------------------
# Operational values, all overridable. A personal, low-traffic app scales to zero
# when idle (min=0) and is capped so a runaway loop can't fan out unbounded cost.
MIN_INSTANCES="${MIN_INSTANCES:-0}"
MAX_INSTANCES="${MAX_INSTANCES:-4}"
CONCURRENCY="${CONCURRENCY:-80}"

# --- Health probes (SOT-2804) -----------------------------------------------
# Startup probe gives the container time to import the app + bind $PORT before the
# first liveness check; liveness restarts an unresponsive instance. Both hit the
# unauthenticated /health endpoint (no external calls, PII-free).
HEALTH_PATH="${HEALTH_PATH:-/health}"
CONTAINER_PORT="${CONTAINER_PORT:-8080}"
STARTUP_PROBE="httpGet.path=${HEALTH_PATH},httpGet.port=${CONTAINER_PORT},initialDelaySeconds=${STARTUP_INITIAL_DELAY:-2},periodSeconds=${STARTUP_PERIOD:-5},timeoutSeconds=${STARTUP_TIMEOUT:-3},failureThreshold=${STARTUP_FAILURES:-12}"
LIVENESS_PROBE="httpGet.path=${HEALTH_PATH},httpGet.port=${CONTAINER_PORT},periodSeconds=${LIVENESS_PERIOD:-30},timeoutSeconds=${LIVENESS_TIMEOUT:-3},failureThreshold=${LIVENESS_FAILURES:-3}"

# Structured logging level for the app (SOT-2804).
LOG_LEVEL="${LOG_LEVEL:-INFO}"

# Secret Manager secret names (create these before first deploy):
#   pcca-auth-secret        -> AUTH_SECRET        (HMAC key for session cookies)
#   pcca-allowed-emails     -> ALLOWED_USER_EMAILS (comma-separated allow-list)
#   pcca-firebase-api-key   -> FIREBASE_API_KEY    (Firebase Web API key for REST auth)
SECRETS="${SECRETS:-AUTH_SECRET=pcca-auth-secret:latest,ALLOWED_USER_EMAILS=pcca-allowed-emails:latest,FIREBASE_API_KEY=pcca-firebase-api-key:latest}"

# Non-secret runtime configuration.
ENV_VARS="APP_ENV=production"
ENV_VARS="${ENV_VARS},LOG_LEVEL=${LOG_LEVEL}"
ENV_VARS="${ENV_VARS},PCCA_PERSISTENCE=firestore"
ENV_VARS="${ENV_VARS},GOOGLE_GENAI_USE_VERTEXAI=true"
ENV_VARS="${ENV_VARS},GOOGLE_CLOUD_PROJECT=${PROJECT_ID}"
ENV_VARS="${ENV_VARS},GOOGLE_CLOUD_LOCATION=${VERTEX_LOCATION}"
ENV_VARS="${ENV_VARS},FIRESTORE_DATABASE=${FIRESTORE_DATABASE:-(default)}"
if [ -n "${CORS_ORIGINS:-}" ]; then
  ENV_VARS="${ENV_VARS},CORS_ORIGINS=${CORS_ORIGINS}"
fi

echo "== Cloud Run deploy: ${SERVICE} =="
echo "Project: ${PROJECT_ID} | Region: ${REGION} | Vertex: ${VERTEX_LOCATION}"

# Cloud Build builds the Dockerfile and pushes the image; --source . uses this repo.
gcloud run deploy "${SERVICE}" \
  --source . \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --port="${CONTAINER_PORT}" \
  --set-secrets="${SECRETS}" \
  --set-env-vars="${ENV_VARS}" \
  --memory="${MEMORY:-512Mi}" \
  --cpu="${CPU:-1}" \
  --timeout="${TIMEOUT:-300}" \
  --min-instances="${MIN_INSTANCES}" \
  --max-instances="${MAX_INSTANCES}" \
  --concurrency="${CONCURRENCY}" \
  --startup-probe="${STARTUP_PROBE}" \
  --liveness-probe="${LIVENESS_PROBE}" \
  --quiet

echo ""
echo "Scale: min=${MIN_INSTANCES} max=${MAX_INSTANCES} concurrency=${CONCURRENCY} | probes: /health (startup+liveness)"

SERVICE_URL=$(gcloud run services describe "${SERVICE}" \
  --region="${REGION}" --project="${PROJECT_ID}" \
  --format='value(status.url)' 2>/dev/null || echo "")

echo ""
echo "== Deploy complete =="
echo "Service URL: ${SERVICE_URL:-N/A}"
if [ -n "${SERVICE_URL}" ]; then
  echo "Smoke check: curl -fsS ${SERVICE_URL}/health  # expect {\"status\":\"ok\"}"
fi
