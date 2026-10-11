# Terraform owns the secret metadata. Real credentials are written directly to
# Vault by the owner; subsequent plans must never reset that secret version.
resource "oci_vault_secret" "runtime" {
  compartment_id = var.compartment_ocid
  vault_id       = var.vault_ocid
  key_id         = var.vault_key_ocid
  secret_name    = "home-movies-runtime"
  description    = "Private application settings; content managed outside Terraform"
  secret_content {
    content_type = "BASE64"
    content      = base64encode("{}")
  }
  lifecycle {
    ignore_changes  = [secret_content]
    prevent_destroy = true
  }
}
