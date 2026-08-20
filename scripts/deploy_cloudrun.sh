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

# Secret Manager secret names (create these before first deploy):
#   pcca-auth-secret        -> AUTH_SECRET        (HMAC key for session cookies)
#   pcca-allowed-emails     -> ALLOWED_USER_EMAILS (comma-separated allow-list)
#   pcca-firebase-api-key   -> FIREBASE_API_KEY    (Firebase Web API key for REST auth)
SECRETS="${SECRETS:-AUTH_SECRET=pcca-auth-secret:latest,ALLOWED_USER_EMAILS=pcca-allowed-emails:latest,FIREBASE_API_KEY=pcca-firebase-api-key:latest}"

# Non-secret runtime configuration.
ENV_VARS="APP_ENV=production"
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
  --set-secrets="${SECRETS}" \
  --set-env-vars="${ENV_VARS}" \
  --memory="${MEMORY:-512Mi}" \
  --timeout="${TIMEOUT:-300}" \
  --quiet

SERVICE_URL=$(gcloud run services describe "${SERVICE}" \
  --region="${REGION}" --project="${PROJECT_ID}" \
  --format='value(status.url)' 2>/dev/null || echo "")

echo ""
echo "== Deploy complete =="
echo "Service URL: ${SERVICE_URL:-N/A}"
if [ -n "${SERVICE_URL}" ]; then
  echo "Smoke check: curl -fsS ${SERVICE_URL}/health  # expect {\"status\":\"ok\"}"
fi
