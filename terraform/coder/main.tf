terraform {
  required_version = ">= 1.10" # use_lockfile (S3-native state locking) needs Terraform >= 1.10

  required_providers {
    coderd = {
      source  = "coder/coderd"
      version = "~> 0.0"
    }
  }

  # Remote state on Hetzner Object Storage (S3-compatible / Ceph-RGW).
  # Credentials via AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY from ssegning-aws.
  # See docs/patterns/coder-declarative-templates.md "State backend".
  #
  # Modern (Terraform >= 1.6) flag names: `endpoint` -> `endpoints.s3`,
  # `force_path_style` -> `use_path_style`. `use_lockfile` gives S3-native state
  # locking; verify Ceph-RGW honours conditional writes (If-None-Match).
  backend "s3" {
    bucket = "ssegning-k8s-state"
    key    = "coder/templates/terraform.tfstate"
    region = "us-east-1"

    # S3-compatible (Ceph-RGW) backend flags.
    endpoints                   = { s3 = "https://nbg1.your-objectstorage.com" }
    use_path_style              = true
    use_lockfile                = true # verify Ceph-RGW conditional-write support
    skip_s3_checksum            = true # verify; AWS SDK v2 checksums can break S3-compatible uploads
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
  }
}

provider "coderd" {
  url   = var.coder_url
  token = var.coder_token
}
