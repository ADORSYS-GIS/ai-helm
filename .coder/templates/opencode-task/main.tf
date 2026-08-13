terraform {
  required_version = ">= 1.0"
  required_providers {
    coder = {
      source  = "coder/coder"
      version = ">= 2.13"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.23"
    }
  }
}

# --- PROVIDERS ---
provider "kubernetes" {
  # If Coder is running INSIDE k3s (same cluster), use the service account token
  # This is the standard setup for k3s deployments
  host                   = "https://kubernetes.default.svc"
  cluster_ca_certificate = file("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
  token                  = file("/var/run/secrets/kubernetes.io/serviceaccount/token")

  # If Coder is OUTSIDE k3s, comment out the above and uncomment below:
  # config_path = "~/.kube/config"
}

provider "coder" {}

# --- DATA SOURCES ---
data "coder_workspace" "me" {}
data "coder_workspace_owner" "me" {}
data "coder_task" "me" {}

# --- VARIABLES ---
variable "opencode_url" {
  type        = string
  description = "opencode server URL. opencode fetches remote config + auth metadata from <this>/.well-known/opencode (serves the camer-digital provider, agents, MCP servers, models)."
  default     = "https://ai.camer.digital/opencode"
}

variable "provider_key" {
  type        = string
  description = "Provider/server id used by @vymalo/opencode-oauth2 as the cache file stem (serverId) — must match the provider key in the remote config served by opencode_url."
  default     = "camer-digital"
}

variable "workdir" {
  type        = string
  description = "Working directory"
  default     = "/home/coder/project"
}

# --- KEYCLOAK OAUTH2 VARIABLES ---
variable "namespace" {
  type        = string
  description = "Kubernetes namespace for the workspace pod (defaults to prod 'coder'; override to 'coder-flows' for local test)"
  default     = "coder"
}

variable "coder_agent_url" {
  type        = string
  description = "In-cluster Coder server URL for the workspace agent to reach the coderd server. Leave empty to use the public access URL (e.g. prod). For local NodePort-only deployments set e.g. http://coder.coder-flows.svc:80"
  default     = ""
}

# --- LOCALS ---
locals {
  workdir = trimsuffix(var.workdir, "/")

  # The opencode server base URL (without trailing slash). opencode fetches its
  # remote config from <opencode_url>/.well-known/opencode, which serves the
  # camer-digital provider, agents, MCP servers and models.
  opencode_url = trimsuffix(var.opencode_url, "/")

  # Decode the workspace owner's Keycloak OIDC access token to get the `sub`
  # (identity) and the `billing_plan`. The `coder` client carries a
  # `billing_plan` claim via the billing-plan client-scope protocol mapper.
  owner_token   = data.coder_workspace_owner.me.oidc_access_token
  owner_payload = jsondecode(base64decode(split(".", local.owner_token)[1]))
  owner_sub     = local.owner_payload.sub
  billing_plan  = try(local.owner_payload.billing_plan, "free")

  # Per-workspace ServiceAccount: identity (sub) + plan in the NAME so Authorino
  # can derive both via pure CEL (kubernetesTokenReview) — no SA-label read / no
  # K8s-API metadata call (which is operationally fragile: CA trust + token RBAC
  # + per-request API call). Format: coder-<sub>.<plan> — the `.` separates the
  # owner sub from the plan (UUIDs/plans never contain `.`), making the parse
  # robust to any sub length. The `coder-` prefix marks it as a workspace SA.
  sa_name = "coder-${local.owner_sub}.${local.billing_plan}"

  # OpenCode uses a DUMMY key and points at the local openresty sidecar, which
  # injects the real SA token. The wellknown auth entry (with a dummy token)
  # still triggers the remote-config fetch so agents/MCP/models load.
  opencode_auth = jsonencode({
    (local.opencode_url) = {
      type  = "wellknown"
      key   = "OPENAI_API_KEY"
      token = "dummy-key"
    }
  })

  # Local provider override forces opencode to the sidecar (localhost) with the
  # dummy key. The remote config supplies agents/MCP/models; this wins on the
  # provider baseURL.
  opencode_config = jsonencode({
    "$schema" = "https://opencode.ai/config.json"
    logLevel  = "DEBUG"
    provider = {
      (var.provider_key) = {
        options = {
          baseURL = "http://localhost:8080/v1"
          apiKey  = "dummy-key"
        }
      }
    }
    permission = {
      edit = "allow"
      bash = "allow"
    }
  })
}

resource "coder_agent" "main" {
  arch = "amd64"
  os   = "linux"

  # CRITICAL: Install Node.js (required for OpenCode). No OAuth cache pre-seed
  # is needed — OpenCode uses a dummy key through the local openresty sidecar,
  # which injects the real SA token at the gateway.
  startup_script = <<-EOT
    set -e

    # 1. Install Node.js (Required for OpenCode)
    if command -v apt-get &> /dev/null; then
      sudo apt-get update
      sudo apt-get install -y curl gnupg
      curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
      sudo apt-get install -y nodejs
    fi

    # 2. Install basic tools
    sudo apt-get install -y git build-essential

    # 3. Verify installation
    node --version
    npm --version
  EOT
}
# --- KUBERNETES POD (The Actual Container) ---
# --- PER-WORKSPACE SERVICEACCOUNT (identity + plan carrier) ---
resource "kubernetes_service_account_v1" "workspace" {
  metadata {
    name      = local.sa_name
    namespace = var.namespace
  }
}

# --- OPENRESTY SIDECAR CONFIG ---
resource "kubernetes_config_map_v1" "nginx_conf" {
  metadata {
    name      = "coder-${data.coder_workspace.me.id}-nginx-conf"
    namespace = var.namespace
  }
  data = {
    # openresty reads the projected SA token file PER REQUEST (Lua), so token
    # rotation is picked up automatically — stock Caddy's {file.read} does not
    # resolve in header_up (verified), so openresty is the rotation-safe proxy.
    "nginx.conf" = <<-EOT
      worker_processes 1;
      # pid + temp dirs must go to a writable path under the read-only root FS
      # (the sidecar-tmp emptyDir mounted at /tmp). Single-level paths so nginx
      # can create them (it does not mkdir intermediate dirs).
      pid /tmp/nginx.pid;
      error_log /dev/stdout info;
      events { worker_connections 1024; }
      http {
          client_body_temp_path /tmp/cbt;
          proxy_temp_path /tmp/proxy;
          fastcgi_temp_path /tmp/fastcgi;
          uwsgi_temp_path /tmp/uwsgi;
          scgi_temp_path /tmp/scgi;
          access_log /dev/stdout;
          server {
              listen 8080;
              location = /healthz {
                  default_type text/plain;
                  return 200 "ok\\n";
              }
              location / {
                  access_by_lua_block {
                      ngx.req.clear_header("Authorization");
                      ngx.req.clear_header("X-Coder-User");
                      ngx.req.clear_header("X-LibreChat-User");
                      ngx.req.clear_header("X-Account-Id");
                      ngx.req.clear_header("X-Org-Id");
                      ngx.req.clear_header("X-Billing-Plan");
                      local f = io.open("/var/run/secrets/gateway-token/token", "r")
                      local token = f:read("*a"); f:close()
                      token = token:gsub("%s+", "")
                      ngx.req.set_header("Authorization", "Bearer " .. token)
                  }
                  proxy_pass https://core-gateway-internal.envoy-gateway-system.svc;
                  proxy_ssl_trusted_certificate /etc/internal-ca/ca.crt;
              }
          }
      }
    EOT
  }
}

# This is what was missing!
resource "kubernetes_pod_v1" "workspace" {
  count = data.coder_workspace.me.start_count

  metadata {
    # Fix: Use a guaranteed RFC 1123 compliant name
    # Option A: Use Workspace ID (UUID) - Safest
    name = "coder-${data.coder_workspace.me.id}"

    # Option B (Alternative): If you prefer readable names, use a hash to avoid special chars
    # name      = "coder-${substr(md5("${data.coder_workspace_owner.me.name}-${data.coder_workspace.me.name}"), 0, 16)}"

    namespace = var.namespace
    labels = {
      "app" = "coder-workspace"
    }
  }
  spec {
    restart_policy       = "Always" # Changed from Never to keep workspace alive
    service_account_name = local.sa_name

    container {
      name  = "workspace"
      image = "codercom/enterprise-base:ubuntu"

      # Run the agent init script
      command = ["/bin/sh", "-c", coder_agent.main.init_script]

      env {
        name  = "CODER_AGENT_TOKEN"
        value = coder_agent.main.token
      }

      dynamic "env" {
        for_each = var.coder_agent_url != "" ? [1] : []
        content {
          name  = "CODER_AGENT_URL"
          value = var.coder_agent_url
        }
      }

      # OpenCode uses a dummy key through the local openresty sidecar; no real
      # credential is present in this container.
      env {
        name  = "OPENCODE_BASE_URL"
        value = "http://localhost:8080/v1"
      }
      env {
        name  = "OPENCODE_API_KEY"
        value = "dummy-key"
      }

      resources {
        requests = {
          cpu    = "500m"
          memory = "1Gi"
        }
        limits = {
          cpu    = "2"
          memory = "4Gi"
        }
      }
    }

    # openresty sidecar — reads the projected SA token PER REQUEST and injects
    # it as Bearer; forwards (TLS to the internal gateway, trusting its CA).
    # Holds no user credential itself.
    container {
      name  = "sidecar"
      image = "openresty/openresty:alpine"
      args  = ["nginx", "-g", "daemon off;", "-c", "/etc/nginx/nginx.conf"]

      security_context {
        run_as_non_root            = true
        run_as_user                = 101
        run_as_group               = 101
        read_only_root_filesystem  = true
        allow_privilege_escalation = false
        capabilities {
          drop = ["ALL"]
        }
      }

      volume_mount {
        name       = "gateway-token"
        mount_path = "/var/run/secrets/gateway-token"
        read_only  = true
      }
      volume_mount {
        name       = "nginx-conf"
        mount_path = "/etc/nginx/nginx.conf"
        sub_path   = "nginx.conf"
        read_only  = true
      }
      volume_mount {
        name       = "internal-ca"
        mount_path = "/etc/internal-ca"
        read_only  = true
      }
      # nginx buffers proxy bodies/responses + pid; needs a writable tmp under a
      # read-only root FS.
      volume_mount {
        name       = "sidecar-tmp"
        mount_path = "/tmp"
      }
    }

    volume {
      name = "gateway-token"
      projected {
        sources {
          service_account_token {
            audience           = "core-gateway-internal"
            expiration_seconds = 3600
            path               = "token"
          }
        }
      }
    }
    volume {
      name = "nginx-conf"
      config_map {
        name = kubernetes_config_map_v1.nginx_conf.metadata[0].name
      }
    }
    volume {
      name = "sidecar-tmp"
      empty_dir {}
    }
    volume {
      name = "internal-ca"
      secret {
        # The internal-CA Certificate (deps/coder base) produces this secret in
        # the coder namespace; its ca.crt is the root that signs the api-internal
        # listener, so the sidecar trusts it to reach core-gateway-internal.
        secret_name = "coder-internal-ca"
      }
    }

    dns_policy = "ClusterFirst"
  }
}

# --- OPENCODE MODULE ---
module "opencode" {
  source  = "registry.coder.com/coder-labs/opencode/coder"
  version = "0.1.2"

  agent_id             = coder_agent.main.id
  workdir              = local.workdir
  opencode_version     = "latest"
  ai_prompt            = data.coder_task.me.prompt != "" ? data.coder_task.me.prompt : ""
  report_tasks         = true
  install_agentapi     = true
  agentapi_version     = "v0.11.2"
  web_app_display_name = "OpenCode"
  icon                 = "/icon/opencode.svg"
  config_json          = local.opencode_config
  auth_json            = local.opencode_auth
}

# --- TASK RESOURCE ---
resource "coder_ai_task" "opencode_task" {
  app_id = module.opencode.task_app_id
}
