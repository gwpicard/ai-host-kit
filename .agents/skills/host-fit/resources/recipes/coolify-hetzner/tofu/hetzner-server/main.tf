terraform {
  required_version = "= 1.13.2"
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "= 1.70.2"
    }
  }
}

variable "place_name" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,61}[a-z0-9]$", var.place_name))
    error_message = "Use a lower-case place name with letters, digits and hyphens."
  }
}
variable "location" {
  type = string
  validation {
    condition     = contains(["fsn1", "nbg1", "hel1"], var.location)
    error_message = "Use a German or Finnish location."
  }
}
variable "server_type" {
  type = string
}
variable "ssh_public_key" {
  type = string
  validation {
    condition     = startswith(var.ssh_public_key, "ssh-ed25519 ")
    error_message = "Supply an existing Ed25519 public key, never a private key."
  }
}
variable "tailnet_auth_key" {
  type      = string
  sensitive = true
  validation {
    condition     = can(regex("^tskey-auth-[A-Za-z0-9-]+$", var.tailnet_auth_key))
    error_message = "Supply a one-off Tailscale auth key through the hidden prompt."
  }
}
variable "tailnet_key_settings" {
  type = object({ reusable = bool, ephemeral = bool, preauthorised = bool, tags = set(string), expiry_seconds = number, shortest_available = bool })
  validation {
    condition = !var.tailnet_key_settings.reusable && !var.tailnet_key_settings.ephemeral && var.tailnet_key_settings.preauthorised && var.tailnet_key_settings.tags == toset(["tag:server"]) && var.tailnet_key_settings.expiry_seconds > 0 && var.tailnet_key_settings.shortest_available
    error_message = "Use a single-use, pre-approved, non-ephemeral tag:server key, with the shortest available expiry that covers apply."
  }
}
locals {
  ownership  = { purpose = "ai-host-kit", place = var.place_name }
  cloud_init = replace(replace(file("${path.module}/cloud-init.sh"), "{{TAILSCALE_KEY_B64}}", base64encode(var.tailnet_auth_key)), "{{PLACE_NAME}}", var.place_name)
}
resource "hcloud_ssh_key" "place" {
  name       = var.place_name
  public_key = var.ssh_public_key
  labels     = local.ownership
}
resource "hcloud_firewall" "coolify" {
  name   = "coolify"
  labels = local.ownership
  # No inbound rules: tailnet relay connections originate from the server.
  lifecycle {
    ignore_changes = [rule]
  }
}
resource "hcloud_server" "place" {
  name         = var.place_name
  location     = var.location
  server_type  = var.server_type
  image        = "ubuntu-24.04"
  ssh_keys     = [hcloud_ssh_key.place.id]
  firewall_ids = [hcloud_firewall.coolify.id]
  user_data    = local.cloud_init
  labels       = local.ownership
  public_net {
    ipv4_enabled = true
    ipv6_enabled = false
  }
  lifecycle {
    ignore_changes = [user_data]
    precondition {
      condition     = !can(regex("\\{\\{[^}]+\\}\\}", local.cloud_init))
      error_message = "Cloud-init contains an unset placeholder."
    }
  }
}
output "server_id" { value = hcloud_server.place.id }
output "firewall_id" { value = hcloud_firewall.coolify.id }
output "ssh_key_id" { value = hcloud_ssh_key.place.id }
output "ipv4_address" { value = hcloud_server.place.ipv4_address }
output "cloud_init" {
  value = local.cloud_init
  sensitive = true
}
