# Opt in in stages: prepare resources, register the VM, then enable update jobs.
# No service-provided/default profile: it could enroll unrelated instances or
# attach content outside the reviewed OS-only source.
locals {
  osmh_ksplice_sources = toset(["ol9_ksplice-aarch64", "ol9_aarch64_userspace_ksplice-aarch64"])
  osmh_ksplice_source_ids = var.osmh_enabled ? {
    for name in local.osmh_ksplice_sources : name => oci_os_management_hub_software_source.vendor[name].id
  } : {}
}

data "oci_os_management_hub_software_sources" "vendor" {
  for_each             = var.osmh_enabled ? var.osmh_vendor_sources : toset([])
  compartment_id       = var.tenancy_ocid
  display_name         = each.key
  software_source_type = ["VENDOR"]
  os_family            = ["ORACLE_LINUX_9"]
  arch_type            = ["AARCH64"]
  vendor_name          = "ORACLE"
}

resource "oci_os_management_hub_software_source" "vendor" {
  for_each                  = data.oci_os_management_hub_software_sources.vendor
  compartment_id            = var.compartment_ocid
  software_source_type      = "VENDOR"
  origin_software_source_id = one(each.value.software_source_collection[0].items).id
}

resource "oci_os_management_hub_software_source" "operating_system" {
  count                        = var.osmh_enabled ? 1 : 0
  compartment_id               = var.compartment_ocid
  display_name                 = "home-movies-ol9-arm64-os-only"
  software_source_type         = "CUSTOM"
  is_automatically_updated     = true
  is_latest_content_only       = true
  is_created_from_package_list = false
  # Oracle documents that automatic dependency resolution can override excludes.
  is_auto_resolve_dependencies = false
  dynamic "vendor_software_sources" {
    for_each = { for name, source in oci_os_management_hub_software_source.vendor : name => source if !contains(local.osmh_ksplice_sources, name) }
    content {
      id           = vendor_software_sources.value.id
      display_name = vendor_software_sources.value.display_name
    }
  }
  custom_software_source_filter {
    package_filters {
      filter_type          = "EXCLUDE"
      package_name_pattern = "caddy*"
    }
  }
}

resource "oci_os_management_hub_managed_instance_group" "operating_system" {
  count               = var.osmh_enabled ? 1 : 0
  compartment_id      = var.compartment_ocid
  display_name        = "home-movies-os-patching"
  vendor_name         = "ORACLE"
  os_family           = "ORACLE_LINUX_9"
  arch_type           = "AARCH64"
  location            = "OCI_COMPUTE"
  software_source_ids = [oci_os_management_hub_software_source.operating_system[0].id]
  # This API field is creation-only; the explicit attachment action owns later
  # Ksplice additions. Live scheduling/reboot guards enforce exact membership.
  lifecycle { ignore_changes = [software_source_ids] }
}

resource "oci_os_management_hub_managed_instance_group_attach_software_sources_management" "ksplice" {
  count                     = var.osmh_enabled ? 1 : 0
  managed_instance_group_id = oci_os_management_hub_managed_instance_group.operating_system[0].id
  software_sources          = values(local.osmh_ksplice_source_ids)
  work_request_details { display_name = "home-movies-enable-ksplice-content" }
  lifecycle { prevent_destroy = true }
}

resource "oci_os_management_hub_profile" "operating_system" {
  count                     = var.osmh_enabled ? 1 : 0
  compartment_id            = var.compartment_ocid
  display_name              = "home-movies-ol9-arm64"
  profile_type              = "GROUP"
  registration_type         = "OCI_LINUX"
  is_default_profile        = false
  managed_instance_group_id = oci_os_management_hub_managed_instance_group.operating_system[0].id
  depends_on                = [oci_os_management_hub_managed_instance_group_attach_software_sources_management.ksplice]
}

resource "oci_identity_policy" "osmh_instance" {
  count          = var.osmh_enabled ? 1 : 0
  compartment_id = var.compartment_ocid
  name           = "home-movies-os-management"
  description    = "The Home Movies instance may access only its own OSMH record"
  statements = [
    "Allow dynamic-group id ${oci_identity_dynamic_group.runtime.id} to {OSMH_MANAGED_INSTANCE_ACCESS} in compartment id ${var.compartment_ocid} where request.principal.id = target.managed-instance.id",
  ]
}

data "oci_core_services" "oracle_network" {
  count = var.osmh_enabled ? 1 : 0
  filter {
    name   = "name"
    values = ["All .* Services In Oracle Services Network"]
    regex  = true
  }
}

resource "oci_core_service_gateway" "operating_system" {
  count          = var.osmh_enabled ? 1 : 0
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.application.id
  display_name   = "home-movies-oracle-services"
  services { service_id = one(data.oci_core_services.oracle_network[0].services).id }
}

resource "oci_os_management_hub_scheduled_job" "operating_system" {
  count          = var.osmh_updates_enabled ? 1 : 0
  compartment_id = var.compartment_ocid
  display_name   = "home-movies-os-updates"
  description    = "All OS package updates from the OS-only source; Caddy excluded"
  # Patch this VM only, even if an administrator later adds other group members.
  managed_instance_ids = [oci_core_instance.web.id]
  schedule_type        = "RECURRING"
  recurring_rule       = "${var.osmh_update_recurring_rule};BYHOUR=${var.osmh_update_hour_utc};BYMINUTE=${var.osmh_update_minute_utc};BYSECOND=0"
  time_next_execution  = var.osmh_update_start
  retry_intervals      = [5, 5, 5]
  # Both named Ksplice repositories are attached alongside the filtered OS source.
  operations { operation_type = "UPDATE_ALL" }
  # The service advances this after every execution. Do not reset it to the
  # original start on unrelated applies; change hours/minutes via the rule.
  lifecycle { ignore_changes = [time_next_execution] }
}
