resource "coderd_template" "poc_ubuntu" {
  name            = "poc-ubuntu"
  display_name    = "POC Ubuntu"
  description     = "Simple Docker POC template (declarative delivery test, ADR-0120)"
  organization_id = var.organization_id

  versions = [{
    name      = "v-${var.git_commit_sha}"
    message   = "Initial declarative test version"
    directory = "${path.root}/../../.coder/templates/poc-ubuntu"
    active    = true
  }]
}

output "poc_ubuntu_template_id" {
  value = coderd_template.poc_ubuntu.id
}

resource "coderd_template" "opencode_task" {
  name            = "opencode-task"
  display_name    = "OpenCode Task"
  description     = "Kubernetes OpenCode workspace, URL-driven and authenticated to the Camer Digital AI gateway (no interactive login), task-capable via the Coder tasks API."
  organization_id = var.organization_id

  versions = [{
    name      = "v-${var.git_commit_sha}"
    message   = "URL-driven TTL OpenCode template"
    directory = "${path.root}/../../.coder/templates/opencode-task"
    active    = true
  }]
}

output "opencode_task_template_id" {
  value = coderd_template.opencode_task.id
}
