terraform {
  required_providers {
    coder = {
      source = "coder/coder"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.23"
    }
  }
}

data "coder_provisioner" "me" {}
data "coder_workspace" "me" {}
data "coder_workspace_owner" "me" {}

provider "coder" {}

# If Coder is running INSIDE the same cluster (k3s), use the service account
# token. This matches the platform's k8s-based workspace delivery (ADR-0122).
provider "kubernetes" {
  host                   = "https://kubernetes.default.svc"
  cluster_ca_certificate = file("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
  token                  = file("/var/run/secrets/kubernetes.io/serviceaccount/token")

  # If Coder is OUTSIDE k3s, comment out the above and uncomment below:
  # config_path = "~/.kube/config"
}

variable "namespace" {
  type        = string
  description = "Kubernetes namespace for the workspace pod"
  default     = "coder"
}

resource "coder_agent" "main" {
  arch = data.coder_provisioner.me.arch
  os   = data.coder_provisioner.me.os

  # Startup script for a minimal shell-only workspace (no IDE).
  startup_script = <<-EOT
    set -e
    sudo apt-get update
    sudo apt-get install -y git curl
  EOT
}

resource "kubernetes_pod_v1" "workspace" {
  count = data.coder_workspace.me.start_count

  metadata {
    name      = "coder-${data.coder_workspace.me.id}"
    namespace = var.namespace
    labels = {
      "app" = "coder-workspace"
    }
  }

  spec {
    restart_policy = "Always"

    container {
      name    = "workspace"
      image   = "codercom/enterprise-base:ubuntu"
      command = ["/bin/sh", "-c", coder_agent.main.init_script]

      env {
        name  = "CODER_AGENT_TOKEN"
        value = coder_agent.main.token
      }

      resources {
        requests = {
          cpu    = "250m"
          memory = "512Mi"
        }
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }
    }
  }
}
