# One-time root authority creates the DG; ordinary infrastructure jobs can only
# manage its existing ID. No OCI permissions are granted to this DG here.
resource "oci_identity_dynamic_group" "runtime" {
  count          = nonsensitive(var.runtime_dynamic_group_ocid) == null ? 1 : 0
  compartment_id = var.tenancy_ocid
  name           = "home-movies-runtime"
  description    = "Home Movies runtime group; transferred to application Terraform"
  matching_rule  = "instance.compartment.id = '${var.compartment_ocid}'"
  lifecycle { prevent_destroy = true }
}

locals {
  runtime_dynamic_group_ocid = var.runtime_dynamic_group_ocid != null ? var.runtime_dynamic_group_ocid : oci_identity_dynamic_group.runtime[0].id
}

resource "oci_identity_policy" "automation" {
  compartment_id = var.tenancy_ocid
  name           = "home-movies-automation"
  description    = "Separate Home Movies infrastructure and deployment authorities"
  statements = [
    "Allow group id ${var.infrastructure_group_ocid} to manage all-resources in compartment id ${var.compartment_ocid}",
    "Allow group id ${var.infrastructure_group_ocid} to read compartments in tenancy where target.compartment.id = '${var.compartment_ocid}'",
    "Allow group id ${var.infrastructure_group_ocid} to inspect objectstorage-namespaces in tenancy",
    "Allow group id ${var.infrastructure_group_ocid} to manage dynamic-groups in tenancy where target.dynamic-group.id = '${local.runtime_dynamic_group_ocid}'",
    "Allow group id ${var.deployment_group_ocid} to inspect objectstorage-namespaces in tenancy",
    "Allow group id ${var.deployment_group_ocid} to read instances in compartment id ${var.compartment_ocid}",
    "Allow group id ${var.deployment_group_ocid} to use instance-agent-command-family in compartment id ${var.compartment_ocid}",
  ]
  lifecycle { prevent_destroy = true }
}

output "runtime_dynamic_group_ocid" {
  value     = local.runtime_dynamic_group_ocid
  sensitive = true
}
