#!/usr/bin/env bash
set -euo pipefail

# Apply the Cloud Monitoring alert policies for the PCCA backend (SOT-2804).
#
# Creates (or, with --update, refreshes) the 5xx error-rate and p95-latency alert
# policies from the JSON definitions in this directory. The service name is substituted
# into each policy's metric filter at apply time.
#
# Usage:
#   GCP_PROJECT_ID=sota-app-hub bash deploy/monitoring/apply_alerts.sh
#   GCP_PROJECT_ID=sota-app-hub NOTIFICATION_CHANNELS=projects/p/notificationChannels/123 \
#     bash deploy/monitoring/apply_alerts.sh
#
# Prerequisites:
#   * gcloud auth login && the Monitoring API enabled on the project.
#   * (optional) NOTIFICATION_CHANNELS — comma-separated channel ids to notify.

PROJECT_ID="${GCP_PROJECT_ID:?GCP_PROJECT_ID is required (e.g. sota-app-hub)}"
SERVICE="${SERVICE:-personal-child-context-agent-backend}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CHANNEL_ARGS=()
if [ -n "${NOTIFICATION_CHANNELS:-}" ]; then
  CHANNEL_ARGS=(--notification-channels="${NOTIFICATION_CHANNELS}")
fi

for policy in alert-error-rate.json alert-latency.json; do
  src="${HERE}/${policy}"
  rendered="$(mktemp)"
  # Substitute the target service name into the metric filter.
  sed "s/__SERVICE__/${SERVICE}/g" "${src}" > "${rendered}"

  echo "== Creating alert policy from ${policy} (service=${SERVICE}) =="
  gcloud monitoring policies create \
    --project="${PROJECT_ID}" \
    --policy-from-file="${rendered}" \
    "${CHANNEL_ARGS[@]}"

  rm -f "${rendered}"
done

echo ""
echo "== Alert policies applied =="
echo "List: gcloud monitoring policies list --project=${PROJECT_ID}"
