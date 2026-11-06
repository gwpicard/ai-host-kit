mock_provider "hcloud" {
  mock_resource "hcloud_firewall" {
    defaults = { id = "101" }
  }
}
variables {
  place_name     = "test-place"
  location       = "fsn1"
  server_type    = "cx23"
  ssh_public_key = "ssh-ed25519 c3ludGhldGlj test"
}
run "fresh" {
  command = plan
  assert {
    condition     = hcloud_firewall.coolify.name == "coolify" && length(hcloud_firewall.coolify.rule) == 0
    error_message = "A fresh place must have no inbound firewall rules."
  }
  assert {
    condition     = hcloud_server.place.firewall_ids == toset([tonumber(hcloud_firewall.coolify.id)])
    error_message = "The firewall must be attached at server creation, before cloud-init."
  }
  assert {
    condition     = !one(hcloud_server.place.public_net).ipv6_enabled
    error_message = "The outside probe currently covers IPv4 only."
  }
  assert {
    condition     = !can(regex("\\{\\{[^}]+\\}\\}", output.cloud_init)) && strcontains(output.cloud_init, "Acquire::ForceIPv4")
    error_message = "Render cloud-init fully and force IPv4 apt."
  }
  assert {
    condition     = strcontains(output.cloud_init, "tailscale ip -4") && !strcontains(output.cloud_init, "--auth-key")
    error_message = "Bootstrap must wait for the tailnet without retaining an enrolment key."
  }
}
