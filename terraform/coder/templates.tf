resource "coderd_template" "poc_ubuntu" {
  name            = "poc-ubuntu"
  display_name    = "POC Ubuntu"
  description     = "Simple Kubernetes POC template (declarative delivery test — ADR-0122)"
  organization_id = var.organization_id

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
