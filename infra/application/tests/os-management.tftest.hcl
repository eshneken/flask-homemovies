mock_provider "oci" {
  mock_resource "oci_os_management_hub_software_source" {
    defaults        = { display_name = "test-vendor-name" }
    override_during = plan
  }
  mock_data "oci_os_management_hub_software_sources" {
    defaults = { software_source_collection = [{ items = [{ id = "test-vendor-source" }] }] }
  }
  mock_data "oci_core_services" {
    defaults = { services = [{ id = "test-oracle-services", cidr_block = "all-iad-services-in-oracle-services-network", name = "All IAD Services In Oracle Services Network" }] }
  }
}
variables {
  deployment_group_ocid = "test-deploy-group"
  tenancy_ocid          = "test-tenancy"
  compartment_ocid      = "test-compartment"
  compartment_name      = "test-compartment-name"
  region                = "us-ashburn-1"
  availability_domain   = "test-ad"
  image_ocid            = "test-image"
  vault_ocid            = "test-vault"
  vault_key_ocid        = "test-key"
  hostname              = "movies.example.com"
  acme_email            = "admin@example.com"
  bastion_client_cidrs  = ["10.0.0.42/32"]
  image_repository      = "ghcr.io/example/home-movies"
}
override_data {
  target = data.oci_identity_compartment.application
  values = { name = "test-compartment-name" }
}
override_resource {
  target          = oci_identity_dynamic_group.runtime
  values          = { id = "test-runtime-group" }
  override_during = plan
}
run "no_unrequested_enrollment_or_jobs" {
  command = plan
  assert {
    condition     = length(oci_os_management_hub_profile.operating_system) == 0 && length(oci_os_management_hub_scheduled_job.operating_system) == 0 && length(oci_core_service_gateway.operating_system) == 0
    error_message = "OSMH must be an explicit opt-in."
  }
}
run "prepare_os_only_content" {
  command = plan
  variables { osmh_enabled = true }
  assert {
    condition     = length(oci_os_management_hub_software_source.vendor) == 5 && oci_os_management_hub_software_source.operating_system[0].software_source_type == "CUSTOM"
    error_message = "Prepare only the reviewed Oracle OS repositories, never Caddy COPR."
  }
  assert {
    condition     = length(oci_os_management_hub_software_source.operating_system[0].vendor_software_sources) == 5 && alltrue([for source in oci_os_management_hub_software_source.operating_system[0].vendor_software_sources : source.display_name == "test-vendor-name"])
    error_message = "OCI requires each custom-source vendor reference to include its display name as well as its ID."
  }
  assert {
    condition     = oci_os_management_hub_software_source.operating_system[0].is_automatically_updated && !oci_os_management_hub_software_source.operating_system[0].is_auto_resolve_dependencies && one(oci_os_management_hub_software_source.operating_system[0].custom_software_source_filter[0].package_filters).filter_type == "EXCLUDE" && one(oci_os_management_hub_software_source.operating_system[0].custom_software_source_filter[0].package_filters).package_name_pattern == "caddy*"
    error_message = "Keep current content while enforcing the Caddy exclusion."
  }
  assert {
    condition     = !oci_os_management_hub_profile.operating_system[0].is_default_profile && length(oci_os_management_hub_scheduled_job.operating_system) == 0 && contains([for p in oci_core_instance.web.agent_config[0].plugins_config : p.name if p.desired_state == "DISABLED"], "OS Management Hub Agent")
    error_message = "Preparation must not enroll instances or schedule updates."
  }
  assert {
    condition     = contains([for r in oci_core_route_table.application.route_rules : r.destination_type], "SERVICE_CIDR_BLOCK") && !oci_core_instance.web.create_vnic_details[0].assign_public_ip && oci_core_instance.web.instance_options[0].are_legacy_imds_endpoints_disabled
    error_message = "OSMH needs private service access; preserve private VM and IMDSv2."
  }
  # Value: protects=OSMH instance authority is self-only and compartment-scoped;
  # fails_when=the self condition or scope broadens or another statement is added;
  # why_new=the new OSMH policy had no independent permission assertion; seam=none;
  # no_claim=mocked Terraform planning does not prove live OCI IAM enforcement.
  assert {
    condition     = oci_identity_policy.osmh_instance[0].compartment_id == "test-compartment" && oci_identity_policy.osmh_instance[0].statements == tolist(["Allow dynamic-group id test-runtime-group to {OSMH_MANAGED_INSTANCE_ACCESS} in compartment id test-compartment where request.principal.id = target.managed-instance.id"])
    error_message = "Grant OSMH access only to this instance's own record in the application compartment."
  }
}
run "enable_registration_separately" {
  command = plan
  variables {
    osmh_enabled           = true
    osmh_register_instance = true
  }
  assert {
    condition     = contains([for p in oci_core_instance.web.agent_config[0].plugins_config : p.name if p.desired_state == "ENABLED"], "OS Management Hub Agent") && length(oci_os_management_hub_scheduled_job.operating_system) == 0
    error_message = "Enrollment must not implicitly enable patching."
  }
}
run "daily_updates_without_unconditional_reboots" {
  command = plan
  variables {
    osmh_enabled           = true
    osmh_register_instance = true
    osmh_updates_enabled   = true
    osmh_update_start      = "2030-01-01T08:00:00Z"
  }
  assert {
    condition     = oci_os_management_hub_scheduled_job.operating_system[0].recurring_rule == "FREQ=DAILY;INTERVAL=1;BYHOUR=8;BYMINUTE=0;BYSECOND=0" && one(oci_os_management_hub_scheduled_job.operating_system[0].operations).operation_type == "UPDATE_ALL" && oci_os_management_hub_scheduled_job.operating_system[0].retry_intervals == tolist([5, 5, 5])
    error_message = "Schedule all OS updates with retries, without implicitly rebooting the VM."
  }
}
run "reject_updates_before_registration" {
  command = plan
  variables {
    osmh_updates_enabled = true
    osmh_update_start    = "2030-01-01T08:00:00Z"
  }
  expect_failures = [var.osmh_updates_enabled]
}
run "reject_registration_before_preparation" {
  command = plan
  variables { osmh_register_instance = true }
  expect_failures = [var.osmh_register_instance]
}
run "reject_missing_schedule_start" {
  command = plan
  variables {
    osmh_enabled           = true
    osmh_register_instance = true
    osmh_updates_enabled   = true
  }
  expect_failures = [var.osmh_update_start]
}
run "reject_caddy_or_wrong_architecture_source" {
  command = plan
  variables { osmh_vendor_sources = ["caddy-copr", "ol9_uekr8-x86_64"] }
  expect_failures = [var.osmh_vendor_sources]
}
