# opencode-task

A Coder template that runs OpenCode in a Coder workspace and authenticates it to
the **internal** Camer Digital AI gateway with **per-user attribution** and no
interactive login and no real credential in the pod. See
**ADR-0130** (`docs/adr/0130-coder-workspace-opencode-internal-sa-auth.md`).

## What it does

- Provisions a two-container pod (`codercom/enterprise-base:ubuntu`) in the
  target namespace: **OpenCode** + an **openresty sidecar**.
- OpenCode points at the sidecar (`localhost:8080`) with a **dummy key**; it
  fetches its full config (the `camer-digital` provider, agents, MCP servers,
  models) from `<opencode_url>/.well-known/opencode`.
- Proves a **per-workspace ServiceAccount** named `coder-<sub>.<plan>.<workspaceId>`
  (the owner's Keycloak `sub`, billing plan, and the workspace UUID in the name;
  the UUID suffix keeps the SA name unique **per workspace**, so a second
  workspace of the same owner — e.g. task-provisioned — doesn't collide on one
  SA name).
- The openresty sidecar reads the projected SA token (audience
  `core-gateway-internal`) **per request** and injects it as `Bearer`, then
  forwards to `core-gateway-internal.envoy-gateway-system.svc` (trusting the
  internal CA).
- **Authorino** validates the SA token (`kubernetesTokenReview`) and derives
  `x-account-id` (the owner `sub`) and `x-billing-plan` (the plan) by pure CEL
  from the SA name — `sub` = `[0]`, `plan` = `[1]`, workspace-UUID segment
  identity-neutral — no SA-label read, no K8s-API metadata call.
- No client secrets, no refresh tokens, and **no owner credential** are ever
  written to the pod.

## Task capability

The template defines a `coder_ai_task` (`app_id = module.opencode.task_app_id`)
and reads the prompt via `data.coder_task.me`, so a task submitted through the
Coder tasks API auto-provisions the workspace and starts the OpenCode agent with
that prompt (`ai_prompt`).

## ⚠️ Ephemeral (no PVC) — deliberate

This is a **task-scoped, ephemeral workspace**: there is no persistent volume.
Every stop/start recreates the pod, wiping `/home/coder/project`, `node_modules`,
and any caches. **Do not store work here — use git.** This is intentional:
a clean, disposable pod means no residual credentials, caches, or state in a
user-controlled environment. If you need a persistent *interactive* OpenCode
workspace, that is a separate template variant (not this one).

## Usage

```bash
coder templates push opencode-task --directory=. --var namespace=coder
```

## Variables

| Variable | Default | Description |
|---|---|---|
| `namespace` | `coder` | Kubernetes namespace for the workspace pod |
| `opencode_url` | `http://models-opencode-wellknown.converse.svc/opencode` | OpenCode server URL; remote config is fetched from `<url>/.well-known/opencode`. **Internal** by default: the public URL (`https://ai.camer.digital/opencode`) does not hairpin through the Hetzner LB from inside the cluster, and opencode re-fetches this config on every session open — a fatal hang. See ADR-0130. |
| `provider_key` | `camer-digital` | Provider key used in the local OpenCode provider override (must match the key in the remote config) |
| `workdir` | `/home/coder/project` | Working directory |
| `model` | `camer-digital/glm-4.7-flash` | Default model for the agent session. MUST be a camer-digital model id. Pinned (not left unset) so opencode can't fall back to a built-in models.dev model the sidecar can't serve (the "invalid api" error). |
| `small_model` | *(empty → defaults to `model`)* | Small/interstitial model (titles, summaries). Must be camer-digital. |
| `camer_models` | the full 22-model catalog | Whitelist of camer-digital model ids (bare). Everything else opencode bundles from models.dev is hidden — only camer-digital models are selectable. Update when the catalog changes. |
| `coder_agent_url` | *(empty)* | In-cluster Coder server URL for the agent (empty = public access URL) |
