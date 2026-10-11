mock_provider "oci" {}
variables {
  tenancy_ocid              = "test-tenancy"
  compartment_ocid          = "test-home-compartment"
  infrastructure_group_ocid = "test-infra-group"
  deployment_group_ocid     = "test-deploy-group"
  region                    = "us-ashburn-1"
}
run "separate_scoped_authorities" {
  command = plan
  override_resource {
    target          = oci_identity_dynamic_group.runtime[0]
    values          = { id = "test-created-runtime-group" }
    override_during = plan
  }
  assert {
    condition     = contains(oci_identity_policy.automation.statements, "Allow group id test-deploy-group to use instance-agent-command-family in compartment id test-home-compartment")
    error_message = "Application deployments need Run Command only in Home Movies."
  }
  assert {
    condition     = !anytrue([for statement in oci_identity_policy.automation.statements : strcontains(statement, "manage all-resources in tenancy")])
    error_message = "No permanent tenancy-wide workload authority is allowed."
  }
  assert {
    condition     = length(oci_identity_policy.automation.statements) == 7
    error_message = "Review additions to automation permissions explicitly."
  }
  assert {
    condition     = contains(oci_identity_policy.automation.statements, "Allow group id test-deploy-group to read objectstorage-namespaces in tenancy") && !anytrue([for s in oci_identity_policy.automation.statements : strcontains(s, "inspect objectstorage-namespaces")])
    error_message = "OCI namespace access supports read, not inspect."
  }
}
run "reuse_transferred_runtime_group" {
  command = plan
  variables { runtime_dynamic_group_ocid = "test-existing-runtime-group" }
  assert {
    condition     = length(oci_identity_dynamic_group.runtime) == 0 && contains(oci_identity_policy.automation.statements, "Allow group id test-infra-group to manage dynamic-groups in tenancy where target.dynamic-group.id = 'test-existing-runtime-group'")
    error_message = "Only the existing runtime group may be managed after the handoff."
  }
}
