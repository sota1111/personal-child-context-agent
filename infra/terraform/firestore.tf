# Named Firestore database `pcca` (SOT-2803).
# Native-mode Firestore in the deployment region. The backend selects this database
# via the FIRESTORE_DATABASE env var (see cloud_run.tf). Collections
# (child_context / school_information / actions) are created on first write and are
# not modeled here. deletion_policy=DELETE lets Terraform manage the resource without
# blocking; flip to the default if you want destroy protection.
resource "google_firestore_database" "pcca" {
  project     = var.project_id
  name        = var.firestore_database
  location_id = var.firestore_location
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.required]
}
