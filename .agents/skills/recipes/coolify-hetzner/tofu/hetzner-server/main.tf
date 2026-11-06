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
locals {
  ownership  = { purpose = "ai-host-kit", place = var.place_name }
  cloud_init = file("${path.module}/cloud-init.sh")
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
output "cloud_init" { value = local.cloud_init }
