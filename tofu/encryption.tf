variable "host_state_passphrase" {
  type = string
  sensitive = true
  ephemeral = true
}
terraform {
  required_version = "= 1.13.2"
  encryption {
    key_provider "pbkdf2" "host" {
      passphrase = var.host_state_passphrase
    }
    method "aes_gcm" "host" {
      keys = key_provider.pbkdf2.host
    }
    state {
      method = method.aes_gcm.host
      enforced = true
    }
    plan {
      method = method.aes_gcm.host
      enforced = true
    }
  }
}
