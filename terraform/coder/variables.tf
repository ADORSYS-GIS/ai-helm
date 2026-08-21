variable "coder_url" {
  type        = string
  description = "Coder deployment URL"
}

variable "coder_token" {
  type        = string
  description = "Coder API token with template-admin scope"
  sensitive   = true
}

variable "git_commit_sha" {
  type        = string
  description = "Git commit SHA used in the template version name (required, so version names stay unique per content change)"
}
