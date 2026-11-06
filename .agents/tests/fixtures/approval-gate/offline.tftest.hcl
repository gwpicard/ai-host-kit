run "local_plan" {
  command = plan
  assert {
    condition = terraform_data.keep.input == var.fixture_value
    error_message = "The local fixture input differs."
  }
}
