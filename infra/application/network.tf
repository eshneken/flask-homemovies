# Dedicated project networking; no grocery resources are referenced or imported.
resource "oci_core_vcn" "application" {
  compartment_id = var.compartment_ocid
  cidr_blocks    = [var.vcn_cidr]
  display_name   = "home-movies"
  dns_label      = "movies"
  lifecycle {
    precondition {
      condition     = data.oci_identity_compartment.application.name == var.compartment_name
      error_message = "Destination compartment name and OCID must match."
    }
  }
}
resource "oci_core_internet_gateway" "application" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.application.id
  display_name   = "home-movies"
  enabled        = true
}
resource "oci_core_route_table" "load_balancer" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.application.id
  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.application.id
  }
}
resource "oci_core_nat_gateway" "application" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.application.id
  display_name   = "home-movies-outbound"
  block_traffic  = false
}
resource "oci_core_route_table" "application" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.application.id
  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_nat_gateway.application.id
  }
}
# Empty security list: inbound access comes only from the explicit NSGs below.
resource "oci_core_security_list" "application" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.application.id
  display_name   = "home-movies-empty"
}
resource "oci_core_subnet" "application" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.application.id
  cidr_block                 = var.subnet_cidr
  display_name               = "home-movies"
  dns_label                  = "web"
  route_table_id             = oci_core_route_table.application.id
  security_list_ids          = [oci_core_security_list.application.id]
  prohibit_public_ip_on_vnic = true
}
resource "oci_core_subnet" "load_balancer" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.application.id
  cidr_block                 = var.load_balancer_subnet_cidr
  display_name               = "home-movies-public-lb"
  dns_label                  = "lb"
  route_table_id             = oci_core_route_table.load_balancer.id
  security_list_ids          = [oci_core_security_list.application.id]
  prohibit_public_ip_on_vnic = false
}
resource "oci_core_network_security_group" "nlb" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.application.id
  display_name   = "home-movies-nlb"
}
resource "oci_core_network_security_group" "web" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.application.id
  display_name   = "home-movies-web"
}
resource "oci_core_network_security_group_security_rule" "public_web" {
  for_each                  = toset(["80", "443"])
  network_security_group_id = oci_core_network_security_group.nlb.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = "0.0.0.0/0"
  source_type               = "CIDR_BLOCK"
  tcp_options {
    destination_port_range {
      min = tonumber(each.value)
      max = tonumber(each.value)
    }
  }
}
resource "oci_core_network_security_group_security_rule" "nlb_to_web" {
  for_each                  = toset(["80", "443", "8080"])
  network_security_group_id = oci_core_network_security_group.nlb.id
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = oci_core_network_security_group.web.id
  destination_type          = "NETWORK_SECURITY_GROUP"
  tcp_options {
    destination_port_range {
      min = tonumber(each.value)
      max = tonumber(each.value)
    }
  }
}
resource "oci_core_network_security_group_security_rule" "web_from_nlb" {
  for_each                  = toset(["80", "443", "8080"])
  network_security_group_id = oci_core_network_security_group.web.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = oci_core_network_security_group.nlb.id
  source_type               = "NETWORK_SECURITY_GROUP"
  tcp_options {
    destination_port_range {
      min = tonumber(each.value)
      max = tonumber(each.value)
    }
  }
}
resource "oci_core_network_security_group_security_rule" "web_https_egress" {
  network_security_group_id = oci_core_network_security_group.web.id
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}
resource "oci_core_network_security_group_security_rule" "web_http_egress" {
  network_security_group_id = oci_core_network_security_group.web.id
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  tcp_options {
    destination_port_range {
      min = 80
      max = 80
    }
  }
}

# OCI's link-local VCN resolver, including TCP fallback for larger DNS responses.
resource "oci_core_network_security_group_security_rule" "web_dns_tcp" {
  network_security_group_id = oci_core_network_security_group.web.id
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = "169.254.169.254/32"
  destination_type          = "CIDR_BLOCK"
  tcp_options {
    destination_port_range {
      min = 53
      max = 53
    }
  }
}
resource "oci_core_network_security_group_security_rule" "web_dns_udp" {
  network_security_group_id = oci_core_network_security_group.web.id
  direction                 = "EGRESS"
  protocol                  = "17"
  destination               = "169.254.169.254/32"
  destination_type          = "CIDR_BLOCK"
  udp_options {
    destination_port_range {
      min = 53
      max = 53
    }
  }
}
resource "oci_core_network_security_group_security_rule" "web_time" {
  network_security_group_id = oci_core_network_security_group.web.id
  direction                 = "EGRESS"
  protocol                  = "17"
  destination               = "169.254.169.254/32"
  destination_type          = "CIDR_BLOCK"
  udp_options {
    destination_port_range {
      min = 123
      max = 123
    }
  }
}
