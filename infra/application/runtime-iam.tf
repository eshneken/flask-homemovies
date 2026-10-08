# Dynamic groups have tenancy scope. Match only this VM, never the whole compartment.
resource "oci_identity_dynamic_group" "runtime" {
  compartment_id = var.tenancy_ocid
  name           = "home-movies-runtime"
  description    = "Home Movies VM only: runtime secret and its Run Command executions"
  matching_rule  = "instance.id = '${oci_core_instance.web.id}'"
}
resource "oci_identity_policy" "runtime" {
  compartment_id = var.compartment_ocid
  name           = "home-movies-runtime"
  description    = "Access one runtime secret and this instance's own Run Command executions"
  statements = [
    "Allow dynamic-group id ${oci_identity_dynamic_group.runtime.id} to read secret-bundles in compartment id ${var.compartment_ocid} where target.secret.id = '${var.runtime_secret_ocid}'",
    "Allow dynamic-group id ${oci_identity_dynamic_group.runtime.id} to use instance-agent-command-execution-family in compartment id ${var.compartment_ocid} where request.instance.id = target.instance.id",
  ]
}
