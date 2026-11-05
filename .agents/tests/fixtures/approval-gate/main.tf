variable "fixture_value" {
  type = string
  default = "first fixture"
}
variable "fixture_secret" {
  type = string
  sensitive = true
}
resource "terraform_data" "keep" {
  input = var.fixture_value
  triggers_replace = var.fixture_value
}
resource "terraform_data" "secret" {
  input = var.fixture_secret
}
output "hidden" {
  value = var.fixture_secret
  sensitive = true
}
