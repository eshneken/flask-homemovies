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
variable "region" { type = string }
variable "runtime_dynamic_group_ocid" {
  type      = string
  sensitive = true
  default   = null
}
variable "oci_auth" {
  type    = string
  default = "SecurityToken"
  validation {
    condition     = contains(["SecurityToken", "APIKey"], var.oci_auth)
    error_message = "Use SecurityToken or a reviewed initial bootstrap API profile."
  }
}
variable "config_file_profile" {
  type    = string
  default = "HOMEMOVIES"
}
variable "availability_domain" {
  type      = string
  sensitive = true
}
variable "image_ocid" {
  type      = string
  sensitive = true
}
variable "runtime_secret_ocid" {
  type      = string
  sensitive = true
}
variable "hostname" {
  type      = string
  sensitive = true
  validation {
    condition     = can(regex("^[a-zA-Z0-9][a-zA-Z0-9.-]+[a-zA-Z0-9]$", var.hostname))
    error_message = "Supply only a DNS hostname, without scheme, port or shell characters."
  }
}
variable "acme_email" {
  type      = string
  sensitive = true
  validation {
    condition     = can(regex("^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+$", var.acme_email))
    error_message = "Supply a valid certificate contact email."
  }
}
variable "vcn_cidr" {
  type    = string
  default = "10.42.0.0/16"
}
variable "subnet_cidr" {
  type    = string
  default = "10.42.1.0/24"
}

variable "load_balancer_subnet_cidr" {
  type    = string
  default = "10.42.2.0/24"
}

variable "bastion_client_cidr" {
  type      = string
  sensitive = true
  validation {
    condition     = can(cidrhost(var.bastion_client_cidr, 0)) && can(regex("^[0-9.]+/32$", var.bastion_client_cidr))
    error_message = "Allow only the operator's current IPv4 address as a /32 CIDR."
  }
}

variable "image_repository" {
  type = string
  validation {
    condition     = can(regex("^ghcr[.]io/[a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*$", var.image_repository))
    error_message = "Supply only the project's GHCR image repository, without tag or digest."
  }
}
