output "state_namespace" {
  value     = data.oci_objectstorage_namespace.current.namespace
  sensitive = true
}
output "state_bucket_name" {
  value     = oci_objectstorage_bucket.state.name
  sensitive = true
}
output "vault_ocid" {
  value     = oci_kms_vault.application.id
  sensitive = true
}
output "vault_key_ocid" {
  value     = oci_kms_key.runtime.id
  sensitive = true
}
