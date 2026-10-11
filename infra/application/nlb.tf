resource "oci_network_load_balancer_network_load_balancer" "web" {
  compartment_id                 = var.compartment_ocid
  display_name                   = "home-movies"
  subnet_id                      = oci_core_subnet.load_balancer.id
  is_private                     = false
  is_preserve_source_destination = false
  network_security_group_ids     = [oci_core_network_security_group.nlb.id]
}
resource "oci_network_load_balancer_backend_set" "web" {
  for_each                 = toset(["80", "443"])
  network_load_balancer_id = oci_network_load_balancer_network_load_balancer.web.id
  name                     = "web-${each.value}"
  policy                   = "FIVE_TUPLE"
  is_preserve_source       = false
  health_checker {
    protocol           = "HTTP"
    port               = 8080
    url_path           = "/health"
    return_code        = 200
    interval_in_millis = 10000
    timeout_in_millis  = 3000
    retries            = 3
  }
}
resource "oci_network_load_balancer_backend" "web" {
  for_each                 = toset(["80", "443"])
  network_load_balancer_id = oci_network_load_balancer_network_load_balancer.web.id
  backend_set_name         = oci_network_load_balancer_backend_set.web[each.value].name
  target_id                = oci_core_instance.web.id
  port                     = tonumber(each.value)
  weight                   = 1
}
resource "oci_network_load_balancer_listener" "web" {
  for_each                 = toset(["80", "443"])
  network_load_balancer_id = oci_network_load_balancer_network_load_balancer.web.id
  name                     = "web-${each.value}"
  default_backend_set_name = oci_network_load_balancer_backend_set.web[each.value].name
  port                     = tonumber(each.value)
  protocol                 = "TCP"
}
