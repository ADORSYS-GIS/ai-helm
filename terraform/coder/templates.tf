resource "coderd_template" "poc_ubuntu" {
  name         = "poc-ubuntu"
  display_name = "POC Ubuntu"
  # No organization_id: the provider falls back to the deployment's default org
  # (defaulting it to a string like `default` would fail — the field is a UUID).
  description = "Simple Kubernetes POC template (declarative delivery pilot)"

  versions = [{
    name      = "v-${var.git_commit_sha}"
    message   = "Initial declarative test version" # `message`, NOT `description` (invalid inside `versions`)
    directory = "${path.root}/../../.coder/templates/poc-ubuntu"
    active    = true
    # provisioner_tags = []  # optional: route this version's build to a specific provisioner
  }]
}

output "poc_ubuntu_template_id" {
  value = coderd_template.poc_ubuntu.id
}
