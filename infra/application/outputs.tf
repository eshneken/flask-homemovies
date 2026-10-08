output "instance_ocid" {
  value     = oci_core_instance.web.id
  sensitive = true
}
output "nlb_addresses" {
  value     = oci_network_load_balancer_network_load_balancer.web.ip_addresses
  sensitive = true
}

output "bastion_ocid" {
  value     = oci_bastion_bastion.maintenance.id
  sensitive = true
}
output "private_ip" {
  value     = oci_core_instance.web.private_ip
  sensitive = true
}
output "runtime_secret_ocid" {
  value     = oci_vault_secret.runtime.id
  sensitive = true
}
