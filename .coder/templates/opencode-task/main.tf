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
variable "openai_base_url" {
  type        = string
  description = "OpenAI-compatible API endpoint URL"
  default     = "https://api.ai.camer.digital/v1"
}

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

variable "openai_api_key" {
  type        = string
  description = "API key for the OpenAI-compatible endpoint"
  sensitive   = true
  default     = ""
}

variable "model" {
  type        = string
  description = "Model to use (must be a model routed on the AI gateway; see https://api.ai.camer.digital/v1/models)"
  default     = "adorsys-coder"
}

variable "workdir" {
  type        = string
  description = "Working directory"
  default     = "/home/coder/project"
}

# --- KEYCLOAK OAUTH2 VARIABLES ---
variable "keycloak_issuer_url" {
  type        = string
  description = "Keycloak realm issuer URL"
  default     = "https://auth.verif.fyi/realms/camer-digital"
}

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
  # camer-digital provider, agents, MCP servers and models — so we do NOT hand
  # build a provider block here anymore.
  opencode_url = trimsuffix(var.opencode_url, "/")

  # The workspace owner's own Coder/Keycloak OIDC access token (aud=coder).
  # The AI gateway accepts any valid realm token (verified), so no token
  # exchange is needed. NO secrets are passed to the pod — the token is the
  # only credential present, and it is the user's own.
  owner_token = data.coder_workspace_owner.me.oidc_access_token

  # Seed opencode's credential store with a "wellknown" entry keyed by the
  # opencode server URL. On startup opencode sets OPENAI_API_KEY to this token
  # (auth.env) and fetches the remote config from <url>/.well-known/opencode,
  # which provides the camer-digital provider (audience/oauth2), agents, models
  # and MCP servers. This is exactly what `opencode auth login <url>` writes,
  # but done non-interactively here.
  opencode_auth = jsonencode({
    (local.opencode_url) = {
      type  = "wellknown"
      key   = "OPENAI_API_KEY"
      token = local.owner_token
    }
  })

  # Minimal local config. The provider (camer-digital) comes from the remote
  # config fetched from the URL; we only set runtime defaults/permissions here.
  opencode_config = jsonencode({
    "$schema" = "https://opencode.ai/config.json"
    logLevel  = "DEBUG"
    permission = {
      edit = "allow"
      bash = "allow"
    }
  })
}

resource "coder_agent" "main" {
  arch = "amd64"
  os   = "linux"

  # CRITICAL: Install Node.js + pre-seed OAuth plugin cache
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

    # 3. Pre-seed opencode so no interactive login / device-code prompt ever
    #    fires inside the workspace. Two pieces:
    #
    #    a) OPENCODE_OAUTH_AUTH_JSON -> $HOME/.local/share/opencode/auth.json has
    #       a "wellknown" entry keyed by the opencode URL. opencode reads this on
    #       startup: it sets OPENAI_API_KEY to the owner token and fetches the
    #       remote config from <url>/.well-known/opencode (camer-digital provider,
    #       agents, MCP servers, models). Path is $HOME/.local/share/opencode/auth.json.
    #
    #    b) The @vymalo/opencode-oauth2 plugin cache is pre-seeded with the same
    #       token so any oauth2 path uses a valid Bearer. NO refresh token and NO
    #       client secret are written — only the user's own access token (aud=coder,
    #       accepted by the gateway). Cache path mirrors the plugin's
    #       resolveDefaultCacheRoot(): $XDG_CACHE_HOME ?? ~/.cache, then
    #       opencode-oauth2/<namespace>/<serverId>.json.
    #
    # NOTE: the cache root is computed INSIDE node (os.homedir() + XDG) — never via
    # Terraform $$ escaping, which previously rendered a mangled "35HOME/.cache"
    # path and wrote the seed to the wrong directory.

    # (a) Wellknown auth entry -> enables remote config fetch from the URL
    if [ -n "$${OPENCODE_OAUTH_AUTH_JSON:-}" ]; then
      mkdir -p "$$HOME/.local/share/opencode"
      printf '%s\n' "$${OPENCODE_OAUTH_AUTH_JSON}" > "$$HOME/.local/share/opencode/auth.json"
      chmod 0600 "$$HOME/.local/share/opencode/auth.json"
      echo "seeded auth.json (wellknown)"
    fi

    # (b) oauth2 plugin cache under <serverId>.json (serverId = camer-digital)
    node -e '
      const fs = require("fs");
      const path = require("path");
      const os = require("os");
      const token = process.env.OPENCODE_OAUTH_ACCESS_TOKEN;
      if (!token) { console.error("OPENCODE_OAUTH_ACCESS_TOKEN not set"); process.exit(1); }
      // Mirror @vymalo/opencode-oauth2 resolveDefaultCacheRoot()
      const root = process.env.XDG_CACHE_HOME || path.join(os.homedir(), ".cache");
      const dir = path.join(root, "opencode-oauth2", process.env.OPENCODE_OAUTH_NAMESPACE);
      fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
      const file = path.join(dir, process.env.OPENCODE_OAUTH_SERVER_ID + ".json");
      // NOTE: intentionally NO expiresAt. This oauth2 plugin (device_code flow,
      // not a machine flow) treats a cached token WITHOUT expiresAt as always
      // valid (oauth/client.js#isTokenValid returns true), so it never triggers
      // a device-code prompt or a refresh attempt. The token we inject is a
      // long-TTL (or delivered-fresh-each-start) owner token whose real lifetime
      // is governed by Keycloak, so we must not let the plugin re-auth based on
      // its own expiry bookkeeping.
      const tokenObj = { accessToken: token, tokenType: "Bearer" };
      const data = { serverId: process.env.OPENCODE_OAUTH_SERVER_ID, models: [], rawModels: [], token: tokenObj };
      fs.writeFileSync(file, JSON.stringify(data, null, 2) + "\n", { mode: 0o600 });
      console.log("seeded cache " + file + " (no expiresAt; plugin treats as always-valid)");
    '

    # 4. Verify installation
    node --version
    npm --version
  EOT
}
# --- KUBERNETES POD (The Actual Container) ---
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
    restart_policy = "Always" # Changed from Never to keep workspace alive

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

      env {
        name  = "CAMER_API_KEY"
        value = var.openai_api_key
      }

      # Owner's own OIDC access token for the @vymalo/opencode-oauth2 plugin
      # cache. This is the user's own token (aud=coder) — No client secret and
      # no refresh token are provided to the pod; only this short-lived token.
      env {
        name  = "OPENCODE_OAUTH_ACCESS_TOKEN"
        value = local.owner_token
      }

      # JSON containing the "wellknown" auth entry (keyed by opencode URL) so the
      # startup script can write $HOME/.local/share/opencode/auth.json. This is
      # what makes opencode fetch the remote config from the URL automatically.
      env {
        name  = "OPENCODE_OAUTH_AUTH_JSON"
        value = local.opencode_auth
      }

      env {
        name  = "OPENCODE_OAUTH_NAMESPACE"
        value = "opencode-oauth2-model-sync"
      }

      env {
        name  = "OPENCODE_OAUTH_SERVER_ID"
        value = var.provider_key
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
