terraform {
  required_providers {
    coder = {
      source  = "coder/coder"
      version = "~> 2.13"
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

# Coder's provisioner job runs INSIDE the cluster, so the hashicorp/kubernetes
# provider auto-detects the in-cluster service-account config — no explicit
# host/token/ca needed here. For local `validate`/`plan` it falls back to
# KUBECONFIG or ~/.kube/config, so it doesn't fail outside the pod.
provider "kubernetes" {}

variable "namespace" {
  type        = string
  description = "Kubernetes namespace for the workspace pod"
  default     = "coder"
}

resource "coder_agent" "main" {
  arch = data.coder_provisioner.me.arch
  os   = data.coder_provisioner.me.os

  # `codercom/enterprise-base:ubuntu` already ships git + curl, so no package
  # install is needed for this POC. Pod is ephemeral (no PVC) by design.
  startup_script = <<-EOT
    set -e
    echo "poc-ubuntu workspace ready"
  EOT
}

resource "kubernetes_pod_v1" "workspace" {
  count = data.coder_workspace.me.start_count

  metadata {
    name      = "coder-workspace-${data.coder_workspace.me.id}"
    namespace = var.namespace
    labels = {
      "app" = "coder-workspace"
    }
  }

  spec {
    # Coder's own template uses `Never`: a failed startup surfaces as *stopped*
    # rather than a restart-looping pod — a loud failure is more useful here.
    restart_policy                  = "Never"
    automount_service_account_token = false

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
