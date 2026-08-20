# PCCA infrastructure as code (Terraform) — SOT-2803

Terraform definitions for the Personal Child Context Agent backend infrastructure,
codifying what was previously provisioned by hand with `gcloud`
(`scripts/deploy_cloudrun.sh`, `deploy/`). This is the reproducible source of truth for:

- **Cloud Run v2 service** `personal-child-context-agent-backend` — runtime SA, secret
  env vars, non-secret config, `/health` startup + liveness probes, scale 0→4,
  concurrency 80, 512Mi / 1 CPU, 300s timeout, public (`allUsers` invoker).
- **Named Firestore database** `pcca` (native mode).
- **Secret Manager containers** `pcca-auth-secret`, `pcca-allowed-emails`,
  `pcca-firebase-api-key` — **containers only; values are never in code or state**.
- **Runtime service account** + IAM: `roles/secretmanager.secretAccessor` (per-secret),
  `roles/datastore.user`, `roles/aiplatform.user`.
- **Enabled APIs**: run, firestore, secretmanager, aiplatform, iam, cloudbuild,
  artifactregistry, cloudresourcemanager, monitoring.

## Files

| File | Purpose |
| --- | --- |
| `versions.tf` | Terraform + Google provider (`~> 6.0`) constraints |
| `providers.tf` | Google provider (project/region from vars) |
| `variables.tf` | All inputs; defaults match production |
| `apis.tf` | `google_project_service` API enablement |
| `service_account.tf` | Runtime SA + IAM bindings |
| `secrets.tf` | Secret Manager containers (no versions) |
| `firestore.tf` | Named Firestore database `pcca` |
| `cloud_run.tf` | Cloud Run v2 service + public invoker |
| `outputs.tf` | Service URL, SA email, db name, secret ids |
| `terraform.tfvars.example` | Copy to `terraform.tfvars` and edit |

## Secret values (out-of-band — never in Terraform)

Terraform manages only the secret *containers*. Create/rotate the **values** with
`gcloud` (or the console) so they never touch config or state:

```bash
PROJECT=gen-lang-client-0243034020
printf '%s' "$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  | gcloud secrets versions add pcca-auth-secret --data-file=- --project="$PROJECT"
printf '%s' "you@example.com" \
  | gcloud secrets versions add pcca-allowed-emails --data-file=- --project="$PROJECT"
printf '%s' "<firebase-web-api-key>" \
  | gcloud secrets versions add pcca-firebase-api-key --data-file=- --project="$PROJECT"
```

(If a secret container does not yet exist, `terraform apply` creates it first, then
add a version as above.)

## First-time use / importing the existing (hand-built) infra

The infra already exists (built by `deploy_cloudrun.sh`). To make `terraform plan`
match reality **without recreating anything**, import each live resource into state.

> Confirm `project_id`, `region`, `firestore_database`, and `container_image` in
> `terraform.tfvars` match the **actual** live values first. The variable defaults
> encode the SOT-2803 spec (`gen-lang-client-0243034020` / `asia-northeast1` /
> named db `pcca`); if the live project or database id differs, override them before
> importing or the import addresses below won't resolve.

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # then edit values
terraform init

PROJECT=gen-lang-client-0243034020
REGION=asia-northeast1
SA=pcca-backend-runtime@${PROJECT}.iam.gserviceaccount.com

# APIs (repeat per service listed in apis.tf)
terraform import 'google_project_service.required["run.googleapis.com"]'            "${PROJECT}/run.googleapis.com"
terraform import 'google_project_service.required["firestore.googleapis.com"]'      "${PROJECT}/firestore.googleapis.com"
terraform import 'google_project_service.required["secretmanager.googleapis.com"]'  "${PROJECT}/secretmanager.googleapis.com"
terraform import 'google_project_service.required["aiplatform.googleapis.com"]'     "${PROJECT}/aiplatform.googleapis.com"
terraform import 'google_project_service.required["iam.googleapis.com"]'            "${PROJECT}/iam.googleapis.com"
terraform import 'google_project_service.required["cloudbuild.googleapis.com"]'     "${PROJECT}/cloudbuild.googleapis.com"
terraform import 'google_project_service.required["artifactregistry.googleapis.com"]' "${PROJECT}/artifactregistry.googleapis.com"
terraform import 'google_project_service.required["cloudresourcemanager.googleapis.com"]' "${PROJECT}/cloudresourcemanager.googleapis.com"
terraform import 'google_project_service.required["monitoring.googleapis.com"]'     "${PROJECT}/monitoring.googleapis.com"

# Runtime service account
terraform import google_service_account.runtime \
  "projects/${PROJECT}/serviceAccounts/${SA}"

# Secret containers
terraform import 'google_secret_manager_secret.secrets["AUTH_SECRET"]'         "projects/${PROJECT}/secrets/pcca-auth-secret"
terraform import 'google_secret_manager_secret.secrets["ALLOWED_USER_EMAILS"]' "projects/${PROJECT}/secrets/pcca-allowed-emails"
terraform import 'google_secret_manager_secret.secrets["FIREBASE_API_KEY"]'    "projects/${PROJECT}/secrets/pcca-firebase-api-key"

# Named Firestore database
terraform import google_firestore_database.pcca \
  "projects/${PROJECT}/databases/pcca"

# Cloud Run service
terraform import google_cloud_run_v2_service.backend \
  "projects/${PROJECT}/locations/${REGION}/services/personal-child-context-agent-backend"

# Public invoker binding
terraform import 'google_cloud_run_v2_service_iam_member.public_invoker[0]' \
  "projects/${PROJECT}/locations/${REGION}/services/personal-child-context-agent-backend roles/run.invoker allUsers"

# Project IAM bindings + per-secret accessor
terraform import google_project_iam_member.runtime_datastore_user   "${PROJECT} roles/datastore.user serviceAccount:${SA}"
terraform import google_project_iam_member.runtime_aiplatform_user  "${PROJECT} roles/aiplatform.user serviceAccount:${SA}"
terraform import 'google_secret_manager_secret_iam_member.runtime_secret_accessor["AUTH_SECRET"]'         "projects/${PROJECT}/secrets/pcca-auth-secret roles/secretmanager.secretAccessor serviceAccount:${SA}"
terraform import 'google_secret_manager_secret_iam_member.runtime_secret_accessor["ALLOWED_USER_EMAILS"]' "projects/${PROJECT}/secrets/pcca-allowed-emails roles/secretmanager.secretAccessor serviceAccount:${SA}"
terraform import 'google_secret_manager_secret_iam_member.runtime_secret_accessor["FIREBASE_API_KEY"]'    "projects/${PROJECT}/secrets/pcca-firebase-api-key roles/secretmanager.secretAccessor serviceAccount:${SA}"
```

Then:

```bash
terraform plan   # goal: no destructive changes; only benign metadata diffs, if any
```

If the live infra was created with the **default** compute service account (rather
than the dedicated `pcca-backend-runtime` SA) or the **`(default)`** Firestore
database, either (a) migrate the live resources to match this code, or (b) set
`runtime_service_account_id` / `firestore_database` to the live values before import.
The dedicated SA + named `pcca` database are the SOT-2803 target state.

## Applying to a fresh project

For a brand-new project (nothing to import), just:

```bash
terraform init && terraform apply
```

then add the secret **versions** (see above) and deploy the container image with
`scripts/deploy_cloudrun.sh` (or push an image and set `container_image`).

## Notes

- **Secrets never in state**: only `google_secret_manager_secret` (container) is
  managed — no `google_secret_manager_secret_version`. Values are added out-of-band.
- **Image is not built by Terraform**: `cloud_run.tf` ignores changes to the
  container image so `deploy_cloudrun.sh` can roll revisions without causing drift.
- **Monitoring alert policies** stay in `deploy/monitoring/` (applied by
  `apply_alerts.sh`); this stack enables the Monitoring API but does not (yet) manage
  the policies as Terraform resources.
