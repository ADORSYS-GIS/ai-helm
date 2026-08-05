# opencode-task

A Coder template that provisions an OpenCode workspace in Kubernetes and
authenticates it to the Camer Digital AI gateway **without any interactive
login**. The template is URL-driven and task-capable, so an OpenCode agent can
be given tasks programmatically (via the Coder tasks API / MCP) with no UI.

## What it does

- Provisions a `codercom/enterprise-base:ubuntu` pod in the target namespace.
- Points OpenCode at the opend server URL (`https://ai.camer.digital/opencode`)
  — OpenCode fetches its full config (the `camer-digital` provider, agents, MCP
  servers, models) from `<url>/.well-known/opencode`. No provider block is
  hand-built in the template.
- Authenticates with the workspace owner's own Keycloak OIDC token:
  - Seeds `~/.local/share/opencode/auth.json` with a "wellknown" auth entry
    (keyed by the URL) so OpenCode sets `OPENAI_API_KEY` and fetches remote
    config automatically.
  - Pre-seeds the `@vymalo/opencode-oauth2` plugin cache under
    `opencode-oauth2-model-sync/camer-digital.json` (no `expiresAt` on purpose,
    so the plugin treats the injected token as always-valid and never opens a
    device-code prompt).
- No client secrets and no refresh tokens are ever written to the pod.

## Task capability

The template defines a `coder_ai_task` (`app_id = module.opencode.task_app_id`)
and reads the prompt via `data.coder_task.me`, so a task submitted through the
Coder tasks API (`POST /api/v2/tasks/{user}`) auto-provisions the workspace and
starts the OpenCode agent with that prompt (`ai_prompt`).

## Usage

```bash
# Provision from git (declarative delivery — see terraform/coder/README.md)
# The template is managed from terraform/coder via the coderd_template provider.

# Manual push (alternative)
coder templates push opencode-task --directory=. --var namespace=coder
```

## Variables

| Variable | Default | Description |
|---|---|---|
| `namespace` | `coder` | Kubernetes namespace for the workspace pod (override to `coder-flows` locally) |
| `opencode_url` | `https://ai.camer.digital/opencode` | OpenCode server URL; remote config is fetched from `<url>/.well-known/opencode` |
| `provider_key` | `camer-digital` | Provider/server id used as the oauth2 plugin cache filename (must match the provider key in the remote config) |
| `model` | `adorsys-coder` | Default model name (models come from the remote config) |
| `openai_base_url` | `https://api.ai.camer.digital/v1` | OpenAI-compatible API base URL |
