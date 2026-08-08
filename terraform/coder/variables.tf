variable "coder_url" {
  type        = string
  description = "Coder deployment URL"
  sensitive   = true
}

variable "coder_token" {
  type        = string
  description = "Coder API token with template-admin scope"
  sensitive   = true
}

variable "organization_id" {
  type        = string
  description = "Coder organization ID"
  default     = "default"
}

variable "git_commit_sha" {
  type        = string
  description = "Git commit SHA used in the template version name"
  default     = "dev"
}
