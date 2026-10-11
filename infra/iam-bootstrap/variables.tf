variable "tenancy_ocid" {
  type      = string
  sensitive = true
}
variable "compartment_ocid" {
  type      = string
  sensitive = true
}
variable "infrastructure_group_ocid" {
  type      = string
  sensitive = true
}
variable "deployment_group_ocid" {
  type      = string
  sensitive = true
}
variable "runtime_dynamic_group_ocid" {
  type      = string
  default   = null
  sensitive = true
}
variable "region" { type = string }
variable "oci_auth" {
  type    = string
  default = "SecurityToken"
  validation {
    condition     = var.oci_auth == "SecurityToken"
    error_message = "Initial IAM bootstrap accepts only short-lived session credentials."
  }
}
variable "config_file_profile" {
  type    = string
  default = "HOMEMOVIES"
}
