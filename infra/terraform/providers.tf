# Google provider, parameterised by project + region (SOT-2803).
# Credentials come from the environment (ADC / gcloud auth), never from state.
provider "google" {
  project = var.project_id
  region  = var.region
}
