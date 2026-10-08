variable "tenancy_ocid" {
  type      = string
  sensitive = true
}
variable "compartment_ocid" {
  type      = string
  sensitive = true
}
variable "compartment_name" {
  type      = string
  sensitive = true
}
variable "region" {
  type = string
}
variable "state_bucket_name" {
  type      = string
  sensitive = true
}
variable "oci_auth" {
  type    = string
  default = "SecurityToken"
  validation {
    condition     = contains(["SecurityToken", "APIKey"], var.oci_auth)
    error_message = "Use federated SecurityToken authentication, or a separately reviewed bootstrap API profile."
  }
}
variable "config_file_profile" {
  type    = string
  default = "HOMEMOVIES"
}
