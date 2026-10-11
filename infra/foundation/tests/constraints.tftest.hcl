mock_provider "oci" {}
variables {
  tenancy_ocid      = "test-tenancy"
  compartment_ocid  = "test-compartment"
  compartment_name  = "test-compartment-name"
  region            = "us-ashburn-1"
  state_bucket_name = "example-home-movies-state"
}
override_data {
  target = data.oci_identity_compartment.application
  values = { name = "test-compartment-name" }
}
run "private_state_and_software_key" {
  command = plan
  assert {
    condition     = oci_objectstorage_bucket.state.access_type == "NoPublicAccess" && oci_objectstorage_bucket.state.versioning == "Enabled"
    error_message = "Terraform state must be private and versioned."
  }
  assert {
    condition     = oci_kms_vault.application.vault_type == "DEFAULT" && oci_kms_key.runtime.protection_mode == "SOFTWARE"
    error_message = "Use a standard Vault and software encryption key."
  }
}

run "reject_wrong_compartment" {
  command = plan
  variables {
    compartment_name = "different-compartment"
  }
  expect_failures = [oci_objectstorage_bucket.state]
}
