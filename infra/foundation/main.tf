# The owner-created application compartment is referenced, never managed here.
data "oci_identity_compartment" "application" {
  id = var.compartment_ocid
}

data "oci_objectstorage_namespace" "current" {
  compartment_id = var.tenancy_ocid
}

resource "oci_objectstorage_bucket" "state" {
  compartment_id = var.compartment_ocid
  namespace      = data.oci_objectstorage_namespace.current.namespace
  name           = var.state_bucket_name
  access_type    = "NoPublicAccess"
  storage_tier   = "Standard"
  versioning     = "Enabled"

  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = data.oci_identity_compartment.application.name == var.compartment_name
      error_message = "The supplied compartment OCID and compartment name must match."
    }
  }
}

resource "oci_kms_vault" "application" {
  compartment_id = var.compartment_ocid
  display_name   = "home-movies-runtime"
  vault_type     = "DEFAULT"
  lifecycle {
    prevent_destroy = true
  }
}

resource "oci_kms_key" "runtime" {
  compartment_id      = var.compartment_ocid
  display_name        = "home-movies-runtime"
  management_endpoint = oci_kms_vault.application.management_endpoint
  protection_mode     = "SOFTWARE"
  key_shape {
    algorithm = "AES"
    length    = 32
  }
  lifecycle {
    prevent_destroy = true
  }
}
