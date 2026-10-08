mock_provider "oci" {}
variables {
  tenancy_ocid        = "test-tenancy"
  compartment_ocid    = "test-compartment"
  compartment_name    = "test-compartment-name"
  region              = "us-ashburn-1"
  availability_domain = "test-ad"
  image_ocid          = "test-image"
  runtime_secret_ocid = "test-secret"
  hostname            = "movies.example.com"
  acme_email          = "admin@example.com"
  bastion_client_cidr = "192.0.2.1/32"
  image_repository    = "ghcr.io/example/home-movies"
}
override_data {
  target = data.oci_identity_compartment.application
  values = { name = "test-compartment-name" }
}
run "free_budget_and_private_host" {
  command = plan
  assert {
    condition = (oci_core_instance.web.shape == "VM.Standard.A1.Flex" &&
      oci_core_instance.web.shape_config[0].ocpus == 1 &&
      oci_core_instance.web.shape_config[0].memory_in_gbs == 2 &&
    oci_core_instance.web.source_details[0].boot_volume_size_in_gbs == "50")
    error_message = "Keep the A1 host within the reviewed CPU/RAM/disk budget."
  }
  assert {
    condition     = oci_core_instance.web.instance_options[0].are_legacy_imds_endpoints_disabled
    error_message = "IMDSv1 must always be disabled."
  }
  assert {
    condition     = !oci_core_instance.web.create_vnic_details[0].assign_public_ip && oci_core_subnet.application.prohibit_public_ip_on_vnic
    error_message = "The application VM must have no public IP and its subnet must prohibit them."
  }
  assert {
    condition     = !oci_core_subnet.load_balancer.prohibit_public_ip_on_vnic
    error_message = "The NLB must have a separate public subnet."
  }
  assert {
    condition     = !oci_network_load_balancer_network_load_balancer.web.is_preserve_source_destination
    error_message = "Use full NAT so the VM can restrict inbound traffic to the NLB."
  }
  assert {
    condition     = toset(keys(oci_core_network_security_group_security_rule.public_web)) == toset(["80", "443"])
    error_message = "Expose only HTTP/HTTPS through the NLB."
  }
  assert {
    condition     = toset(keys(oci_core_network_security_group_security_rule.web_from_nlb)) == toset(["80", "443", "8080"])
    error_message = "Only NLB web and health traffic may enter the VM."
  }
  assert {
    condition     = strcontains(base64decode(oci_core_instance.web.metadata.user_data), "127.0.0.1:5000:5000")
    error_message = "The application container must bind only to loopback."
  }
}

run "restricted_maintenance" {
  command = plan
  assert {
    condition     = oci_bastion_bastion.maintenance.max_session_ttl_in_seconds == 3600 && one(oci_bastion_bastion.maintenance.client_cidr_block_allow_list) == "192.0.2.1/32"
    error_message = "Maintenance access must be limited to the operator IP and one-hour sessions."
  }
  assert {
    condition     = contains([for p in oci_core_instance.web.agent_config[0].plugins_config : p.name if p.desired_state == "ENABLED"], "Bastion")
    error_message = "Enable the managed SSH Bastion plugin."
  }
  assert {
    condition     = oci_core_network_security_group_security_rule.ssh_from_bastion.tcp_options[0].destination_port_range[0].min == 22 && oci_core_network_security_group_security_rule.ssh_from_bastion.tcp_options[0].destination_port_range[0].max == 22
    error_message = "The maintenance ingress rule must expose only SSH."
  }
}
run "reject_broad_maintenance_allowlist" {
  command = plan
  variables {
    bastion_client_cidr = "0.0.0.0/0"
  }
  expect_failures = [var.bastion_client_cidr]
}
run "reject_wrong_compartment" {
  command = plan
  variables {
    compartment_name = "different-compartment"
  }
  expect_failures = [oci_core_vcn.application]
}
