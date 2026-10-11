data "oci_identity_compartment" "application" {
  id = var.compartment_ocid
}
resource "oci_core_instance" "web" {
  compartment_id      = var.compartment_ocid
  availability_domain = var.availability_domain
  display_name        = "homemovies-app"
  shape               = "VM.Standard.A1.Flex"
  shape_config {
    ocpus         = 1
    memory_in_gbs = 2
  }
  source_details {
    source_type             = "image"
    source_id               = var.image_ocid
    boot_volume_size_in_gbs = 50
  }
  create_vnic_details {
    subnet_id        = oci_core_subnet.application.id
    assign_public_ip = false # Private application subnet; outbound Internet via NAT gateway.
    nsg_ids          = [oci_core_network_security_group.web.id]
  }
  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }
  agent_config {
    is_management_disabled = false
    plugins_config {
      name          = "Bastion"
      desired_state = "ENABLED"
    }
    plugins_config {
      name          = "Compute Instance Run Command"
      desired_state = "ENABLED"
    }
  }
  metadata = {
    user_data = base64encode(templatefile("${path.module}/templates/cloud-init.yaml.tftpl", {
      hostname          = var.hostname
      acme_email        = var.acme_email
      secret_ocid       = oci_vault_secret.runtime.id
      deploy_helper_b64 = base64encode(file("${path.module}/../../scripts/vm_deploy.py"))
      deploy_config_b64 = base64encode(jsonencode({ hostname = var.hostname, image_repository = var.image_repository }))
    }))
  }
  lifecycle {
    prevent_destroy = true
    # Cloud-init is launch-only. Template edits must not replace a running host;
    # apply equivalent changes to existing hosts through reviewed maintenance.
    ignore_changes = [metadata["user_data"]]
  }
}
