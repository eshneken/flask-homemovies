variable "osmh_enabled" {
  description = "Prepare OS Management Hub resources (requires a Pay As You Go tenancy)."
  type        = bool
  default     = false
}

variable "osmh_register_instance" {
  description = "Enable the plugin and assign this project's profile after preparing IAM/network/content."
  type        = bool
  default     = false
  validation {
    condition     = !var.osmh_register_instance || var.osmh_enabled
    error_message = "Prepare OS Management Hub before enrolling the instance."
  }
}

variable "osmh_updates_enabled" {
  description = "Enable recurring OS updates only after registration and Caddy exclusion are verified."
  type        = bool
  default     = false
  validation {
    condition     = !var.osmh_updates_enabled || (var.osmh_enabled && var.osmh_register_instance)
    error_message = "Register the instance before enabling scheduled updates."
  }
}

variable "osmh_vendor_sources" {
  description = "Only Oracle Linux 9 ARM64 vendor sources; no COPR, EPEL or third-party source."
  type        = set(string)
  default = [
    "ol9_baseos_latest-aarch64", "ol9_appstream-aarch64", "ol9_addons-aarch64",
    "ol9_uekr8-aarch64", "ol9_oci_included-aarch64",
  ]
  validation {
    condition = (alltrue([for source in var.osmh_vendor_sources :
      contains(["ol9_baseos_latest-aarch64", "ol9_appstream-aarch64", "ol9_addons-aarch64", "ol9_uekr8-aarch64", "ol9_oci_included-aarch64"], source)
    ]) && alltrue([for source in ["ol9_baseos_latest-aarch64", "ol9_appstream-aarch64", "ol9_uekr8-aarch64"] : contains(var.osmh_vendor_sources, source)]))
    error_message = "Use reviewed OL9 ARM64 vendor sources including BaseOS latest, AppStream and UEK R8."
  }
}

variable "osmh_update_recurring_rule" {
  description = "Daily or weekly update frequency; hour/minute are configured separately in UTC."
  type        = string
  default     = "FREQ=DAILY;INTERVAL=1"
  validation {
    condition     = contains(["FREQ=DAILY;INTERVAL=1", "FREQ=WEEKLY;INTERVAL=1"], var.osmh_update_recurring_rule)
    error_message = "Choose daily or weekly updates."
  }
}

variable "osmh_update_hour_utc" {
  type        = number
  default     = 8
  description = "UTC hour for package updates (08 UTC is 03 EST / 04 EDT)."
  validation {
    condition     = var.osmh_update_hour_utc >= 0 && var.osmh_update_hour_utc <= 23 && floor(var.osmh_update_hour_utc) == var.osmh_update_hour_utc
    error_message = "The UTC hour must be an integer from 0 to 23."
  }
}

variable "osmh_update_minute_utc" {
  type    = number
  default = 0
  validation {
    condition     = var.osmh_update_minute_utc >= 0 && var.osmh_update_minute_utc <= 59 && floor(var.osmh_update_minute_utc) == var.osmh_update_minute_utc
    error_message = "The UTC minute must be an integer from 0 to 59."
  }
}

variable "osmh_update_start" {
  description = "Explicit future RFC3339 UTC start; required when enabling the schedule."
  type        = string
  default     = null
  validation {
    condition     = !var.osmh_updates_enabled || (can(formatdate("YYYY", var.osmh_update_start)) && can(regex("Z$", var.osmh_update_start)))
    error_message = "Supply a valid RFC3339 UTC start ending in Z before enabling updates."
  }
}
