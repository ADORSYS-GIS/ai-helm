terraform {
  required_version = "~> 1.0"
  required_providers {
    coder = {
      source  = "coder/coder"
      version = "~> 2.13"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
  }
}

# --- PROVIDERS ---
# This template runs inside the Coder provisioner (in-cluster), so the
# kubernetes provider uses the pod's projected service-account token. That makes
# `terraform validate`/`apply` only work in-cluster — the file() paths below do
# not exist outside it. Do not "fix" these validate errors; the provisioner runs
# in-cluster. (ADR-0120's PR-time plan job cannot cover this template dir.)
provider "kubernetes" {
  host                   = "https://kubernetes.default.svc"
  cluster_ca_certificate = file("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
  token                  = file("/var/run/secrets/kubernetes.io/serviceaccount/token")
}

provider "coder" {}

# --- DATA SOURCES ---
data "coder_workspace" "me" {}
data "coder_workspace_owner" "me" {}
data "coder_task" "me" {}

# --- VARIABLES ---
variable "opencode_url" {
  type        = string
  description = "opencode server URL. opencode fetches remote config + auth metadata from <this>/.well-known/opencode (serves the camer-digital provider, agents, MCP servers, models). Defaults to the INTERNAL wellknown service: the public URL (https://ai.camer.digital/opencode) black-holes from inside the cluster (the Hetzner LB does not hairpin — same root cause as coder_agent_url), and opencode re-fetches this on every session open, so a hairpin = a hung session."
  default     = "http://models-opencode-wellknown.converse.svc/opencode"
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

# --- MODEL SELECTION ---
variable "model" {
  type        = string
  description = "The default model OpenCode uses for the agent session (and the small/interstitial model unless overridden). MUST be a camer-digital model id (e.g. camer-digital/glm-4.7-flash). Pinning this (instead of leaving it unset) stops OpenCode from falling back to a built-in models.dev model that the camer-digital sidecar can't serve — which is what surfaces as 'invalid api key' / model-not-found errors."
  default     = "camer-digital/glm-4.7-flash"
}

variable "small_model" {
  type        = string
  description = "The SMALL model OpenCode uses for interstitial/lightweight tasks (titles, summaries, etc). If empty, defaults to the main `model`. Must be a camer-digital model id."
  default     = ""
}

variable "camer_models" {
  type        = list(string)
  description = "The camer-digital model ids (bare, no provider prefix) to whitelist. Everything OpenCode bundles from models.dev for OTHER providers is hidden, so only camer-digital models are selectable — no invalid-api surprises. Default = the catalog currently served by the opencode wellknown. Update this list when the catalog changes."
  default = [
    "adorsys-coder",
    "adorsys-coder-pro-internal",
    "adorsys-frontend",
    "adorsys-planner-internal",
    "adorsys-planner-pro-internal",
    "adorsys-researcher",
    "adorsys-reviewer",
    "adorsys-reviewer-pro-internal",
    "deepseek-v4-flash-0731",
    "gemini-3p1-flash-lite",
    "gemma-4",
    "glm-4.7-flash",
    "glm-5p2-internal",
    "kimi-k2.5",
    "mimo-v2p5",
    "mimo-v2p5-pro",
    "minimax-m2.7",
    "minimax-m2p5",
    "minimax-m3",
    "ornith-1p0-35b",
    "qwen3p7-plus",
    "reviewer-internal",
  ]
}

# --- KEYCLOAK OAUTH2 VARIABLES ---
variable "namespace" {
  type        = string
  description = "Kubernetes namespace for the workspace pod (defaults to prod 'coder'; override to 'coder-flows' for local test)"
  default     = "coder"
}

variable "coder_agent_url" {
  type        = string
  description = "In-cluster Coder server URL for the workspace agent to reach the coderd server. Defaults to the internal coder ClusterIP service (prod); the external access URL (https://coder.ai.camer.digital) black-holes from inside the cluster (the Hetzner LB does not hairpin), so it must NOT be used. For local NodePort-only deployments set e.g. http://coder.coder-flows.svc:80"
  default     = "http://coder.coder.svc.cluster.local"
}

# --- LOCALS ---
locals {
  workdir = trimsuffix(var.workdir, "/")

  # The opencode server base URL (without trailing slash). opencode fetches its
  # remote config from <opencode_url>/.well-known/opencode, which serves the
  # camer-digital provider, agents, MCP servers and models.
  opencode_url = trimsuffix(var.opencode_url, "/")

  # small_model falls back to the main model when not explicitly set. Keeps the
  # interstitial/lightweight calls (title gen, summaries) on camer-digital too.
  effective_small_model = var.small_model != "" ? var.small_model : var.model

  # Decode the workspace owner's Keycloak OIDC access token to get the `sub`
  # (identity) and the `billing_plan`. The `coder` client carries a
  # `billing_plan` claim via the billing-plan client-scope protocol mapper.
  #
  # ⚠️ JWT payload segments are base64url WITHOUT padding, but Terraform's
  # base64decode() requires standard base64 WITH `=` padding — feeding it the
  # raw segment throws, and try() silently swallowed that into the zero-sub
  # placeholder SA (coder-00000000-...free). So we first map the URL-safe
  # alphabet (-_ → +/) and then re-pad to a multiple of 4.
  # try(..., {}) still guards the template-IMPORT dry-run plan, where the
  # provider returns an empty oidc_access_token (no JWT to split) — real
  # workspace builds carry the token, so the real sub/plan are used there.
  owner_token       = data.coder_workspace_owner.me.oidc_access_token
  owner_payload_seg = try(split(".", local.owner_token)[1], "")
  owner_payload_std = replace(replace(local.owner_payload_seg, "-", "+"), "_", "/")
  owner_payload_pad = (4 - length(local.owner_payload_std) % 4) % 4
  owner_payload_b64 = local.owner_payload_pad == 2 ? "${local.owner_payload_std}==" : (local.owner_payload_pad == 1 ? "${local.owner_payload_std}=" : local.owner_payload_std)
  owner_payload     = try(jsondecode(base64decode(local.owner_payload_b64)), {})
  owner_sub         = try(local.owner_payload.sub, "00000000-0000-0000-0000-000000000000")
  billing_plan      = try(local.owner_payload.billing_plan, "free")

  # Per-workspace ServiceAccount: identity (sub) + plan in the NAME so Authorino
  # can derive both via pure CEL (kubernetesTokenReview) — no SA-label read / no
  # K8s-API metadata call (which is operationally fragile: CA trust + token RBAC
  # + per-request API call). Base format: coder-<sub>.<plan> — the `.` separates
  # the owner sub from the plan (UUIDs/plans never contain `.`), making the
  # parse robust to any sub length. The `coder-` prefix marks it as a workspace
  # SA.
  #
  # PER-WORKSPACE uniqueness: append the workspace ID (a UUID — no dots, safe
  # as a third dot-segment). Without it the SA name is keyed to the OWNER
  # (`coder-<sub>.<plan>`), so a SECOND workspace of the same user — e.g. a
  # workspace provisioned by a Coder task the moment one already exists —
  # collides with `serviceaccounts "... "<sub>.<plan>" already exists"` and
  # terraform apply fails (verified: task test-web-link-demo hit exactly this).
  # Authorino's CEL gates (ai-helm-values security-policies.yaml) accept the
  # optional `.workspaceId` segment; `sub` = [0], `plan` = [1] still.
  sa_name = "coder-${local.owner_sub}.${local.billing_plan}.${data.coder_workspace.me.id}"

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
  #
  # CRITICAL: `options.oauth2 = null` — the wellknown config ships an oauth2
  # extension (`authFlow: device_code` for the PUBLIC multi-user opencode that
  # logs in via Keycloak). Without this override, the @vymalo/opencode-oauth2
  # plugin intercepts auth for camer-digital and issues an interactive
  # device-code prompt — which must NOT happen in a workspace whose identity is
  # the injected SA token (dummy key through the sidecar). Setting it to null
  # wins over the merged wellknown value (opencode's merge keeps null), making
  # the plugin inert while agents/MCP/models still sync from the wellknown.
  opencode_config = jsonencode({
    "$schema" = "https://opencode.ai/config.json"
    logLevel  = "DEBUG"
    # Pin the default (and small/interstitial) model to camer-digital. Without
    # this, OpenCode falls back to a built-in models.dev model (e.g.
    # anthropic/...) that the sidecar can't serve — the "invalid api" error.
    model       = var.model
    small_model = local.effective_small_model
    provider = {
      (var.provider_key) = {
        options = {
          baseURL = "http://localhost:8080/v1"
          apiKey  = "dummy-key"
          oauth2  = null
        }
        # Hide every model except the camer-digital ones. opencode bundles 75+
        # providers from models.dev; whitelist is per-provider and here restricts
        # the camer-digital provider to ONLY var.camer_models so a user can't
        # select something the gateway can't serve (invalid-api errors).
        whitelist = var.camer_models
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
  # The image is Ubuntu (codercom/enterprise-base:ubuntu), so apt is present —
  # no guard around the install. Run-as-is: the workspace is ephemeral (no PVC),
  # so this re-runs on each fresh start.
  startup_script = <<-EOT
    set -e

    # 0. Force IPv4 for apt: the workspace pod has no IPv6 default route
    #    (Cilium), so apt's AAAA attempts fail fast with "connect (101: Network
    #    is unreachable)" and never fall back to IPv4. Ubuntu mirrors are only
    #    reachable via IPv4 + HTTP :80 here.
    echo 'Acquire::ForceIPv4 "true";' | sudo tee /etc/apt/apt.conf.d/99force-ipv4 >/dev/null

    # 1. Install Node.js (Required for OpenCode)
    sudo apt-get update
    sudo apt-get install -y curl gnupg
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs

    # 2. Install basic tools
    sudo apt-get install -y git build-essential

    # 3. Verify installation
    node --version
    npm --version

    # 4. Prime opencode's plugin/cache dirs BEFORE the interactive session:
    #    the wellknown config ships 5 bun plugins + npx MCP servers that opencode
    #    auto-installs on first server start. On an ephemeral pod (~/.cache
    #    starts empty) that made the FIRST session open take ~30-60s. Pre-fetch
    #    the wellknown JSON now (also a fast-fail connectivity check for the
    #    internal wellknown pod + its netpol rule — a provision-time failure is
    #    far easier to diagnose than an interactive hang) and let opencode
    #    bootstrap its plugins headlessly (no session, no model call).
    wellknown_url="${local.opencode_url}/.well-known/opencode"
    echo "pre-fetching wellknown config: $wellknown_url"
    curl -fsSL --max-time 15 "$wellknown_url" -o /tmp/opencode-wellknown.json
    export PATH="/home/coder/.opencode/bin:$PATH"
    export OPENCODE_BASE_URL="http://localhost:8080/v1"
    export OPENCODE_API_KEY="dummy-key"
    # Headless bootstrap primes ~/.cache/opencode (plugins + model index) and
    # ~/.cache (npx MCP downloads). Failures here are non-fatal (timeout + || true):
    # worst case the first interactive session performs the install as before.
    timeout 240 opencode models camer-digital >/tmp/opencode-prime.log 2>&1 || true
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
              # Bind loopback-only: the sidecar injects the workspace SA token
              # (the user's gateway credential + identity), so it must not be
              # reachable by other in-cluster workloads. OpenCode connects via
              # localhost:8080 (same pod), so loopback-only is fully compatible.
              listen 127.0.0.1:8080;
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
                  # Envoy Gateway's `api-internal` listener terminates TLS and
                  # matches filter chains BY SNI. nginx sends NO SNI by default,
                  # so Envoy resets the handshake (104) → 502. Worse, the SNI
                  # nginx would derive from proxy_pass (.svc, no .cluster.local)
                  # does NOT match either — the listener is configured for
                  # core-gateway-internal.envoy-gateway-system.svc.cluster.local
                  # exactly. Send that SNI explicitly.
                  proxy_ssl_server_name on;
                  proxy_ssl_name core-gateway-internal.envoy-gateway-system.svc.cluster.local;
                  # HTTPRoute hostnames match on the Host header, not the SNI.
                  # proxy_pass would send Host: <upstream .svc>, which matches
                  # NO route → Envoy 404. The caller reaches us at
                  # localhost:8080, so set the Host to the route hostname the
                  # `-internal` HTTPRoutes are configured with.
                  proxy_set_header Host core-gateway-internal.envoy-gateway-system.svc.cluster.local;
              }
          }
      }
    EOT
  }
}

resource "kubernetes_pod_v1" "workspace" {
  count = data.coder_workspace.me.start_count

  metadata {
    # RFC 1123-compliant pod name derived from the workspace UUID.
    name = "coder-${data.coder_workspace.me.id}"

    namespace = var.namespace
    labels = {
      "app" = "coder-workspace"
    }
  }
  spec {
    restart_policy                  = "Always" # keep the workspace pod alive while running
    service_account_name            = local.sa_name
    automount_service_account_token = false # the pod never calls the k8s API; no default SA token


    container {
      name  = "workspace"
      image = "codercom/enterprise-base:ubuntu"

      # Run the agent. We do NOT use coder_agent.main.init_script: it bakes the
      # PUBLIC access URL into BINARY_URL (https://coder.ai.camer.digital/...),
      # which black-holes from inside the cluster (the Hetzner LB does not
      # hairpin — see the control-plane netpol note). Instead we download the
      # binary from the INTERNAL coder service ($CODER_AGENT_URL), which routes
      # to coderd's :8080 without leaving the cluster.
      command = ["/bin/sh", "-c", <<-EOT
        set -eux
        BINARY_DIR="$${BINARY_DIR:-$(mktemp -d -t coder.XXXXXX)}"
        BINARY_NAME=coder
        BINARY_URL="$${CODER_AGENT_URL}/bin/coder-linux-amd64"
        cd "$$BINARY_DIR"
        while :; do
          if command -v curl >/dev/null 2>&1; then
            curl -fsSL --compressed "$${BINARY_URL}" -o "$${BINARY_NAME}" && break
          else
            echo "error: curl not available"
            exit 127
          fi
          echo "error: failed to download coder agent, retrying in 30s"
          sleep 30
        done
        chmod +x "$${BINARY_NAME}"
        exec ./"$${BINARY_NAME}" agent
      EOT
      ]

      env {
        name  = "CODER_AGENT_TOKEN"
        value = coder_agent.main.token
      }

      # Always set CODER_AGENT_URL (defaults to the internal coder ClusterIP
      # service). Both the binary download above and the agent's connection use
      # it, so we avoid the external access URL / LB hairpin entirely.
      env {
        name  = "CODER_AGENT_URL"
        value = var.coder_agent_url
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
  ai_prompt            = data.coder_task.me.prompt
  report_tasks         = true
  install_agentapi     = true
  agentapi_version     = "v0.11.2"
  web_app_display_name = "OpenCode"
  icon                 = "/icon/opencode.svg"
  # Expose the opencode web app as a WILDCARD app. This deployment has
  # CODER_DISABLE_PATH_APPS=true (ADR-0121), so a `subdomain = false` app is a
  # path-based app pointing at localhost → 403/unreachable (verified: the app
  # reports subdomain_name=None on running workspaces). With `subdomain = true`
  # Coder computes a subdomain_name (e.g. opencode--<workspace>--<user>) and
  # the app is reachable at https://<subdomain_name>.coder-ws.camer.digital via
  # the *.coder-ws.camer.digital wildcard cert — the link the Coder MCP hands
  # back to LibreChat users.
  subdomain   = true
  config_json = local.opencode_config
  auth_json   = local.opencode_auth
}

# --- TASK RESOURCE ---
resource "coder_ai_task" "opencode_task" {
  app_id = module.opencode.task_app_id
}
