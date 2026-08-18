# opencode-web

A **brand-new** Coder template that runs the **opencode native web UI** inside a
Coder workspace, authenticated to the **internal** Camer Digital AI gateway with
**per-user attribution** and no interactive login and no real credential in the
pod (same auth model as ADR-0131).

It deliberately does **NOT** use the `coder-labs/opencode` module / `agentapi`
web-terminal wrapper that the older `opencode-task` template uses — that wrapper
showed a **blank opencode page with no task running** when the workspace-app
link was opened (the agentapi terminal never attached a live session). Instead
this template runs `opencode serve` (opencode's own web app + API, no browser
auto-open) and starts the task **on that same server**, so the web UI shows the
agent working live.

## What it does

- Provisions a two-container pod (`codercom/enterprise-base:ubuntu`) in the
  target namespace: **opencode** + an **openresty sidecar**.
- opencode points at the sidecar (`localhost:8080`) with a **dummy key**; it
  fetches its full config (the `camer-digital` provider, agents, MCP servers,
  models) from `<opencode_url>/.well-known/opencode`.
- Proves a **per-workspace ServiceAccount** named `coder-<sub>.<plan>.<workspaceId>`
  (the owner's Keycloak `sub`, billing plan, and the workspace UUID — the UUID
  keeps the SA name unique per workspace). Authorino derives `x-account-id` /
  `x-billing-plan` from the SA name via pure CEL (see ADR-0131).
- The openresty sidecar reads the projected SA token (audience
  `core-gateway-internal`) **per request** and injects it as `Bearer`, then
  forwards to `core-gateway-internal.envoy-gateway-system.svc`.
- No client secrets, no refresh tokens, and **no owner credential** are ever
  written to the pod.

## The link (what the user / Coder MCP clicks)

The template declares a direct `coder_app` (`slug = "opencode"`,
`subdomain = true`, `share = "owner"`). Coder computes the hostname:

```
https://opencode--<workspace>--<user>.coder-ws.camer.digital
```

e.g. `https://opencode--opencode-web-ws--beniejoypossi.coder-ws.camer.digital`.

**Link-return contract for the Coder MCP / LibreChat agent:** don't hand-assemble
the hostname — read `subdomain_name` from the workspace API after provisioning:

```bash
WSID=$(curl -sS -H "Coder-Session-Token: $TOKEN" \
  "$CODER_URL/api/v2/users/me/workspace/<workspace>" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

curl -sS -H "Coder-Session-Token: $TOKEN" "$CODER_URL/api/v2/workspaces/$WSID" \
| python3 -c '
import sys,json
for r in json.load(sys.stdin)["latest_build"]["resources"]:
    for a in r.get("agents") or []:
        for app in a.get("apps") or []:
            if app.get("slug") == "opencode":
                print(f"https://{app['"'"'subdomain_name'"'"']}.coder-ws.camer.digital")'
```

(`subdomain_name` already includes the `opencode--<ws>--<user>` part — only
append the `https://` scheme and `.coder-ws.camer.digital` suffix.)

## Task flow (start a workspace with a prompt → the agent just works)

1. A task is submitted via the Coder Tasks API
   (`POST /api/v2/tasks/{user}` with `{"input": "<prompt>", "template_version_id": "..."}`)
   — or via the Coder MCP in LibreChat.
2. The workspace auto-provisions. The startup script writes the camer-digital
   config + wellknown auth, primes opencode's caches, and starts
   `opencode serve --port 4096 --hostname 0.0.0.0`.
3. If the task prompt is present (`data.coder_task.me.prompt`), the script runs:

   ```bash
   opencode run --auto --attach http://localhost:4096 --dir <workdir> "<prompt>"
   ```

   The session is created **on the running server** (`--attach`), pinned to the
   project (`--dir`), so the opencode web UI shows it immediately — messages,
   tool calls and file edits stream live. `--auto` auto-approves tool calls so
   the headless agent can actually do the work (without it, the agent stalls
   auto-rejecting every `bash`/file permission request).
4. The user clicks the link above and watches the agent work; they can also
   steer/continue the session from the web UI.

No prompt (workspace created manually) → opencode web starts **idle** and the
user types in the UI.

## ⚠️ Ephemeral (no PVC) — deliberate

Same as `opencode-task`: task-scoped, **no persistent volume**. Every
stop/start recreates the pod, wiping `/home/coder/project` and all caches. **Do
not store work here — use git.**

## Usage

```bash
coder templates push opencode-web --directory=. --var namespace=coder
```

## Variables

| Variable | Default | Description |
|---|---|---|
| `namespace` | `coder` | Kubernetes namespace for the workspace pod |
| `opencode_url` | `http://models-opencode-wellknown.converse.svc/opencode` | opencode server URL; remote config is fetched from `<url>/.well-known/opencode`. **Internal** by default — the public URL does not hairpin from inside the cluster. |
| `opencode_port` | `4096` | Port the opencode web server listens on (declared app + healthcheck) |
| `provider_key` | `camer-digital` | Provider key used in the local provider override (must match the key in the remote config) |
| `workdir` | `/home/coder/project` | Working directory for the web server + task session |
| `model` | `camer-digital/glm-4.7-flash` | Default model for the agent session. MUST be a camer-digital model id (pinned so opencode can't fall back to a models.dev model the sidecar can't serve). |
| `small_model` | *(empty → `model`)* | Small/interstitial model. Must be camer-digital. |
| `camer_models` | the full 22-model catalog | Whitelist of camer-digital model ids (bare). Only these are selectable. |
| `coder_agent_url` | *(empty → internal)* | In-cluster Coder server URL for the agent |

## Verification & troubleshooting

```bash
# In the running workspace:
coder ssh <workspace>
cat /tmp/opencode-serve.log     # web server log
cat /tmp/opencode-task.log      # task session log (if a prompt was submitted)
opencode session list           # confirm the task session exists on the server

# From outside:
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "Coder-Session-Token: $TOKEN" \
  https://opencode--<workspace>--<user>.coder-ws.camer.digital/
# 200 = reachable + permitted (owner). 303 = auth question (layers 1+2 fine).
```

| Symptom | Likely cause |
|---|---|
| Workspace stuck on "Initializing" | **Fixed in current version.** The old startup script waited inline for the server with an un-timeout'd `curl`; the first request to a fresh `opencode serve` triggers heavy plugin/MCP downloads and blocked the script forever. Now serve + wait + task run in a **background bootstrap** (log: `/tmp/opencode-bootstrap.log`) with a bounded, `--max-time`-guarded wait loop (~10 min), so the agent reports ready immediately and the task starts as soon as the server answers. |
| `502` on the link | `opencode serve` not up yet / crashed — check `/tmp/opencode-serve.log` |
| Link loads but no session in the sidebar | No task prompt was submitted (workspace created manually) — the web UI is idle; type in it. If a prompt WAS submitted, check `/tmp/opencode-task.log` + `opencode session list`. |
| Session in sidebar but agent does nothing | `opencode run` missing `--auto` (old version) — the agent auto-rejects every permission request. Rebuild the workspace on the current version. |
| `403` on the link | `subdomain = false` (path app, disabled here) — must stay `true` |
| `404` with a valid session | Share level `owner` + not the owner — see ADR-0121 |
| Model errors (`invalid api key` / model-not-found) | Model not in `camer_models` whitelist, or not camer-digital — update `camer_models` |
| Task API says *"Template does not have a valid coder_ai_task resource"* | The `coder_ai_task` block was removed — it is required |

## Notes

- **Cold start is slow on purpose.** The first request to a fresh `opencode
  serve` downloads the wellknown config's bun plugins + npx MCP servers (can
  take several minutes on a cold pod). The web UI loads slowly the first time,
  then everything is fast; the task session starts in the background once the
  server answers, so a slow warm-up degrades to "task starts late", never
  "stuck".

- **Coder Tasks is deprecated in v2.34** (we run 2.34.6) in favor of Coder
  Agents / the Chats API; Tasks stays supported through the 2.34 ESR window.
  The template keeps `coder_ai_task` (the current working mechanism); the
  `data.coder_task.me.prompt` wiring is the only task-dependent piece, so a
  future Chats-API migration touches just the prompt source.
- See `docs/integrations/coder-workspace-opencode-web-link.md` for the design
  (declared app / link return / task start / auth / watch-vs-interact) and
  ADR-0131 for the auth model.
