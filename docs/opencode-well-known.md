# opencode `.well-known/opencode` at `ai.camer.digital`

How `opencode auth login https://ai.camer.digital/opencode` works in
our stack, and what's required end-to-end to make it land.

**ADR:** [`docs/adr/0014-split-librechart-and-opencode-wellknown.md`](./adr/0014-split-librechart-and-opencode-wellknown.md)
**Chart:** [`charts/librechat-opencode-wellknown`](../charts/librechat-opencode-wellknown/)
**Plugin:** [`@vymalo/opencode-oauth2`](https://www.npmjs.com/package/@vymalo/opencode-oauth2)

## End-to-end flow

```
User on laptop                       Cluster                            Keycloak
─────────────                       ────────                            ────────
$ opencode auth login \
  https://ai.camer.digital/opencode
    │
    │  GET /opencode/.well-known/opencode
    ├──────────────────────────────────►   nginx (librechat-opencode-
    │                                       wellknown chart) serves a
    │                                       static JSON from ConfigMap
    │  { auth: {command: stub}, config: { plugin, provider, oauth2 } }
    │◄──────────────────────────────────
    │
    │  spawns auth.command, captures stdout
    │  (no-op stub returns "plugin-managed")
    │
    │  merges `config` into ~/.opencode/config.json
    │
    │  reads config.plugin → runs `bun install @vymalo/opencode-oauth2`
    │  (auto, cached under ~/.cache/opencode/node_modules/)
    │
    │  loads @vymalo/opencode-oauth2 plugin
    │
    │  plugin sees authFlow=device_code, starts RFC 8628 flow
    │  POST /protocol/openid-connect/auth/device  ───────────────►
    │                                              ◄──────────────  { device_code, user_code, verification_uri }
    │  Prints user_code + URL to terminal
    │
    │  (user opens URL in browser, authenticates, approves)
    │
    │  Polls /token until user approves              ◄──────────────  { access_token, refresh_token }
    │  Caches token at ~/Library/Caches/opencode-oauth2/...
    │
    │  GET https://api.ai.camer.digital/v1/models    ───────────────►  Envoy AI Gateway
    │  Authorization: Bearer <access_token>           (passes Authorino,
    │  ◄────────────────────────────────────────────  forwarded to upstream)
    │  { data: [{id: "glm-5", ...}, ...] }
    │
    │  $ opencode chat
    │  (each request: chat.headers hook injects Bearer)
```

## What the chart deploys

The `librechat-opencode-wellknown` chart deploys:

- A `Deployment` (2 replicas of `nginxinc/nginx-unprivileged:1.27-alpine`,
  10m/16Mi requests, runAsNonRoot, readOnlyRootFilesystem)
- A `Service` (ClusterIP, port 80)
- An `Ingress` (Traefik, host `ai.camer.digital`, path
  `/opencode/.well-known/opencode`, exact-match)
- Two `ConfigMap`s — the nginx config and the well-known JSON content

Total resource footprint: ≈ 50Mi RAM per pod, two pods = 100Mi.
Effectively free.

## The MCP catalog (ADR-0042)

The well-known `config.mcp` block pushes a curated set of MCP servers to every
user — one shared config instead of each person hand-wiring the gateway routes.
opencode merges it *under* the user's own `opencode.json`, so any default is
overridable locally.

| Server | Type | Source | `enabled` (connected) |
|---|---|---|---|
| `brave` | remote | gateway `/mcp/brave` (web search) | `true` |
| `context7` | remote | gateway `/mcp/context7` (library docs) | `true` |
| `terraform` | remote | gateway `/mcp/terraform` (IaC) | `true` |
| `refero` | remote | gateway `/mcp/refero` (design refs) | `true` |
| `firecrawl` | remote | gateway `/mcp/firecrawl` (web scraping) | `false` |

- **Remotes** target the `/mcp/<name>` routes (ADR-0038) and all authenticate
  with the **same** `opencode-cli` Keycloak client
  (`scope: openid profile offline_access`). In `values.yaml` that `oauth` block
  is a YAML anchor (`&mcpOAuth` / `*mcpOAuth`) — declared once, reused; the
  serialized JSON expands it per server. Add a remote by copying three lines,
  never the credential.
- ⚠️ **Since ADR-0044, `enabled` means *connectivity*, not "on for the primary
  agent".** A connected server's tools are denied by the global permission
  baseline and re-allowed only on the role subagent that needs them (see *Agents
  & tool scoping* below) — so `terraform` / `refero` are connected but reachable
  only via `@iac` / `@frontend`, never the default agent. `firecrawl` stays
  unconnected until a role claims it. (ADR-0042 originally shipped only `brave` +
  `context7` connected; ADR-0044 connected the rest as roles needed them.)
- All connected MCP servers are now **remote** (gateway `/mcp/<name>` routes).
  The `chrome-devtools` **local** MCP was removed — live-browser inspection is now
  the `@vymalo/opencode-browser` plugin's `browser_*` tools, owned by `@frontend`.

To verify it reached a server after deploy: `opencode mcp list` shows the merged
catalog; the rendered descriptor's `config.mcp` should match the table above.

## Agents & tool scoping (ADR-0044, token model corrected in ADR-0048)

Tool access is modelled on **two decoupled axes**:

- **Connectivity** — `config.mcp.<name>.enabled` decides whether opencode
  connects to a server at all. A tool only exists if its server is connected, so
  every server a role needs is `enabled: true` (brave, context7, terraform,
  refero); `enabled: false` = not connected (firecrawl, until a role needs it).
- **Access** — a global `config.permission` **deny-baseline** denies every
  connected MCP tool (`brave_*`, `context7_*`, `terraform_*`, `refero_*`)
  plus the `@vymalo/opencode-browser` plugin's `browser_*` tools. Each role is a
  **`mode: subagent`** the primary delegates to (`@name` / the task tool) and a
  **whitelist** that re-allows only its tools + its file/bash scope (per-agent
  permission overrides the root).

> ✅ **Permission scoping IS a per-agent token lever (verified in opencode 1.17.6).**
> opencode filters the **injected** tool set per agent in request-prep:
> `session/llm/request.ts` `resolveTools()` runs every tool name through
> `Permission.disabled()`, which **drops a tool from that agent's injected
> `tools`/`activeTools`** when its effective rule is a `pattern:"*"` **deny**
> (`permission/index.ts`). The filtered set is what's sent to the model — so a
> denied tool costs **zero** tokens for that agent. Mechanics:
> - A config **string-form** `"glob": "deny"` compiles to `{permission:glob,
>   pattern:"*", action:"deny"}` → removes those tools from injection. `"glob":
>   "allow"` re-injects. ⚠️ The **nested** form (`"glob": {sub: "deny"}`) yields a
>   non-`*` pattern → it gates *execution* but does **not** remove from injection.
>   Use the string form for tool gating (we do).
> - An agent's own `permission` merges **after** the root baseline and wins
>   (`findLast`), so the deny-baseline keeps a tool out of every agent **except**
>   the ones that re-`allow` it. This applies uniformly to built-in, MCP, **and
>   plugin** tools (keyed on tool name — `browser_*` included).
> - ⇒ the deny-baseline genuinely makes the **primary agent lean** (those tools
>   are *not injected* into it), and each subagent carries **only its own** tools.
>   The other token lever is **global registration** (don't connect an MCP server
>   / don't register a plugin `group` you'll never allow) — registration gates
>   what *can* be allowed; per-agent permission gates what *is* injected.

| Agent | mode | model | edit | bash | MCP / tools |
|---|---|---|---|---|---|
| `frontend` | **primary** (default) | *inherit* | allow | `ask`; allow JS (`pnpm`/`npm`/`bun`/`yarn`) + Rust/WASM (`cargo`/`trunk`); `rm`→ask | **none** — delegates (lean) |
| `browser` | subagent | **`adorsys-frontend`** (multimodal) | deny | deny | `browser_*` (full page+control, the 27 tools) |
| `design` | subagent | **`adorsys-frontend`** (multimodal) | deny | deny | `refero_*` |
| `web-search` | subagent | *inherit* | deny | deny | `brave_*` |
| `doc-research` | subagent | *inherit* | only `docs/**` | deny | `context7_*` |
| `iac` | subagent | *inherit* | allow | `ask`; allow safe `terraform`/`tofu` (init/validate/plan/fmt); `apply`→ask; `destroy`/`rm *` deny | `context7_*`, `terraform_*` |
| `reviewer` | subagent | *inherit* | deny | deny | `context7_*` |
| `test` | subagent | *inherit* | allow | `ask`; allow common test runners; deny `rm *` | `context7_*` |
| `skill` | subagent | *inherit* | only `.opencode/skills/**`, `skills/**` | deny | `context7_*` + `skill` |

> **`@frontend` is the org-wide default PRIMARY (`config.default_agent`), kept
> lean.** It implements directly (`edit` + JS toolchain) and **delegates** the
> tool-heavy work — so the deny-baseline keeps `browser_*`/`refero_*`/`context7_*`
> out of its injected context (no 27-tool overhead on every turn). The closed loop
> runs **primary implements → `@browser` reloads + screenshots + reports → primary
> decides → iterates**. `@browser` owns the full `browser_*` surface (replacing the
> removed `chrome-devtools` MCP); `@design` owns Refero; library docs route to
> `@doc-research`.
>
> **Model pinning — vision-only (no-risk rule):** pin a multimodal model **only**
> on the agents whose tools return images they must interpret — `@browser`
> (`browser_screenshot`) and `@design` (`refero_get_screen_image`) — so they
> **always** have vision regardless of the session model. **Every other agent**
> (the `frontend` primary *and* all role subagents) carries **no `model`** and
> inherits the user's session model. This drops the old per-role cost-lean pins
> (ADR-0044): simpler and risk-free, at the cost that those roles no longer force a
> cheap model. Only `@browser`/`@design` use the branded `adorsys-frontend` alias
> (`camer-digital/adorsys-frontend` → `charts/ai-models`, swappable there).

> ⚠️ **`bash` permissions are friction, not a sandbox.** opencode matches the
> command **string**, not what the process does. So allow-listing any wrapper
> (`npm */pnpm */bun */yarn */cargo */trunk *`) is effectively arbitrary-code
> execution: `npm run <script>`, `npm exec`, `pnpm exec`, `bun x`, `cargo run`,
> a `build.rs`, or a postinstall hook can delete files **without ever invoking
> `rm`** — so `"rm *": ask` only catches a *directly typed* `rm`, not `rm` routed
> through an allowed command. No per-command rule can close this. Real containment
> is the **environment** (git-tracked worktree, ephemeral/sandboxed run), not the
> permission patterns. Size the allow-list for convenience and assume an allowed
> build tool can do anything its project's scripts can. See
> [`opencode-sandboxing.md`](./opencode-sandboxing.md) for the containment options.

Add a role by copying an `agent` block (+ connecting its server if new). Pin a
model **only** if the role needs vision (the `adorsys-frontend` multimodal alias);
otherwise omit `model` so it inherits the session model. A user can override per
agent locally. Prompts are inline strings (the well-known can't ship prompt
*files*). ⚠️ **Validate runtime
enforcement on a live opencode** (delegate to each role; confirm the primary
lacks the MCP tools and each scope holds) before relying on it — agent-vs-root
permission precedence + MCP-glob gating are opencode-version behaviors.

## Verifying the endpoint after deploy

```bash
curl -fsSL https://ai.camer.digital/opencode/.well-known/opencode | jq
```

Expected:

```json
{
  "auth": {
    "command": ["sh", "-c", "echo plugin-managed"],
    "env": "OPENAI_API_KEY"
  },
  "config": {
    "$schema": "https://opencode.ai/config.json",
    "plugin": ["@vymalo/opencode-oauth2@0.6.3"],
    "provider": {
      "camer-digital": {
        "name": "Camer Digital",
        "options": {
          "baseURL": "https://api.ai.camer.digital/v1",
          "oauth2": {
            "issuer": "https://auth.verif.fyi/realms/camer-digital",
            "clientId": "opencode-cli",
            "scopes": ["openid", "profile", "offline_access"],
            "authFlow": "device_code",
            "syncIntervalMinutes": 60,
            "responseApi": true
          }
        }
      }
    }
  }
}
```

Content-Type must be `application/json` (nginx adds it via
`default_type` in the chart's nginx config).

`oauth2.responseApi` (plugin ≥ 0.6.2,
[vymalo/opencode-oauth2#37](https://github.com/vymalo/opencode-oauth2/pull/37))
is **currently `false`** — inference uses Chat Completions
(`/v1/chat/completions`), the plugin default. It was enabled in
`release-2026.06.13` then turned back off. When `true` it routes inference
through the OpenAI **Responses API** (`/v1/responses`) by registering the
provider with `@ai-sdk/openai` rather than `@ai-sdk/openai-compatible`, and
enables the plugin's streaming SSE index-repair, which supplies the
`output_index`/`content_index` fields our Envoy AI Gateway omits (without
them OpenCode aborts with `text part <id> not found`). It is provider-wide
— every `camer-digital` request would go through `/v1/responses` — and does
not touch the token lifecycle. See the inline comment in
`charts/librechat-opencode-wellknown/values.yaml`.

`meta.modelsInfoOverwrite: ["name"]` (models-info plugin ≥ 0.6.3,
[vymalo/opencode-models-info#38](https://github.com/vymalo/opencode-oauth2/pull/38))
exempts `name` from the plugin's upstream-wins merge. The oauth2 plugin's
model discovery auto-stamps a *normalized* `name` (id `adorsys-coder` →
"Adorsys Coder") before the models-info hook runs, which upstream-wins treats
as handwritten config — so our `/v1/models/info` `name` (each model's branded
`info.displayName`, e.g. "Adorsys Coder (MiniMax M2.7)", ADR-0044) never
landed and the UI showed the plain normalized label. Listing `name` lets the
endpoint value replace it; a field only changes when the endpoint actually
provides one.

## Prerequisites the cluster must satisfy

The chart deploys the endpoint, but two things must exist in Keycloak
for the end-to-end flow to land. These are **out of scope** for this PR
and are tracked separately:

### 1. The `opencode-cli` Keycloak client

In realm `camer-digital`, create a **public** client (no client_secret)
with:

- `clientId: opencode-cli`
- `clientAuthenticatorType: client-secret` (but with `publicClient: true`)
- Device authorization grant **enabled** (the `oauth2.deviceAuthorizationGrantEnabled` setting in Keycloak ≥ 24)
- Default scopes: `openid`, `profile`, `offline_access`
- Redirect URIs: any user-machine-localhost pattern is OK; device-code
  flow doesn't use them, but Keycloak requires the field to be non-empty.
  Suggested: `http://localhost/*`

Add to `charts/keycloak-baseline/values.yaml` once this lands.

### 2. Audience mapper for `lightbridge-api-key`

The `@vymalo/opencode-oauth2` plugin has no `audience` config knob for
non-federated flows. To get `lightbridge-api-key` into the JWT `aud`
claim (so Authorino accepts it on `api.ai.camer.digital`), add a
**client-scope audience mapper**:

- Realm-level client scope: `lightbridge-api-key`
- Mapper: `oidc-audience-mapper`
  - Included audience: `lightbridge-api-key`
  - Add to access token: `ON`
- Attach the scope as a default scope on the `opencode-cli` client

Alternative: enable `token_exchange` flow in the well-known config and
have the plugin exchange the user's identity token for an
audience-correct token. Heavier; only justified if the audience-mapper
approach proves insufficient.

## End-user workflow

```bash
opencode auth login https://ai.camer.digital/opencode
```

That's it. opencode:

1. Fetches `https://ai.camer.digital/opencode/.well-known/opencode`.
2. Reads the `config.plugin` list (currently `["@vymalo/opencode-oauth2", "@vymalo/opencode-models-info"]`)
   and runs `bun install` automatically — the packages are cached under
   `~/.cache/opencode/node_modules/` so this only happens once per
   plugin per machine.
3. Loads the OAuth2 plugin, which kicks off the OAuth 2.0
   device-authorization flow against Keycloak. User code + verification
   URL print to the terminal; user opens the URL in any browser (laptop,
   phone), enters the code, approves.
4. Loads the models-info plugin, which fetches the OpenRouter-shape
   catalog at `https://api.ai.camer.digital/v1/models/info` (ADR-0015,
   served by [`charts/ai-models-info`](../charts/ai-models-info/)) and
   enriches every model with context length, pricing, modalities, and
   capability flags. Cached locally for 24h.
5. Plugin caches the resulting tokens at:
   - macOS: `~/Library/Caches/opencode-oauth2/<namespace>/camer-digital.json`
   - Linux: `$XDG_CACHE_HOME/opencode-oauth2/<namespace>/camer-digital.json`

The cache file is mode `0700` and contains the refresh token. **Treat it
as a credential** — don't commit it, don't sync via Dropbox.

> No manual `opencode plugin add` or `npm install` is required. The
> auto-install behaviour is documented at
> <https://opencode.ai/docs/plugins/> ("npm plugins are installed
> automatically using Bun at startup").

## Why `auth.command` is a stub

opencode's `.well-known/opencode` schema requires `auth.command` for
the `opencode auth login` code path to succeed. Without the plugin,
opencode would spawn this argv and treat stdout as the bearer token,
storing it at `~/.opencode/auth.json` under env-var name `auth.env`.

With the @vymalo plugin loaded, the token in `auth.json` is **never
consulted**. The plugin's `chat.headers` hook overrides the
`Authorization` header per request from its own per-OS cache (see
above). The stub `auth.command` (`sh -c 'echo plugin-managed'`) writes
the literal string `plugin-managed` to opencode's auth.json — harmless,
unused.

If a future opencode version validates the token shape, we'll switch
the stub to emit something parseable. Today it's enough.

## Why `device_code` (not authorization_code)

The plugin's default is `authorization_code`, which binds a localhost
HTTP server to receive the OAuth redirect. That breaks:

- Headless dev machines (no browser)
- Remote dev (SSH'd into a workstation)
- WSL on Windows (port-binding gymnastics)
- Any environment where the user can't easily click a browser link

`device_code` (RFC 8628) prints `https://auth.../device?user_code=ABCD-1234`
to the terminal. The user opens that URL in any browser (including on
their phone), enters the code, and the CLI's poll picks up the token.
Works everywhere.

Trade-off: `device_code` requires Keycloak's device authorization
endpoint enabled (it is, in recent Keycloak releases). And `offline_access`
scope is required so the plugin can refresh the token (see Keycloak
client config above).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `opencode auth login` errors "fetch failed" | Endpoint not reachable | `curl -v https://ai.camer.digital/opencode/.well-known/opencode` from the user's machine. Check DNS / cert / Traefik route. |
| `bun install` fails (no network, registry unreachable) | Auto-install of `@vymalo/opencode-oauth2` blocked | Confirm npm registry reachable. Worst case, pre-seed `~/.cache/opencode/node_modules/@vymalo/opencode-oauth2/` from a known-good machine. |
| `opencode auth login` succeeds but `opencode chat` 401s | Token has wrong audience | Keycloak audience mapper missing (see prereq 2). Decode the JWT (`jwt-cli` or `jwt.io`), check `aud` claim. |
| Plugin says "discovery failed" | Keycloak issuer URL wrong or realm down | Try `curl https://auth.verif.fyi/realms/camer-digital/.well-known/openid-configuration`. |
| "device authorization not enabled" | Keycloak client misconfigured | Enable device-grant on the `opencode-cli` client (see prereq 1). |
| Plugin loop on token refresh | `offline_access` scope not granted | Add to default scopes on the `opencode-cli` client. |
| User-Code URL prints to terminal but never authenticates | User didn't open the URL / approved the wrong device | Re-run `opencode auth login`. |
| 502/504 at `/opencode/.well-known/opencode` | Endpoint pod down | `kubectl get pods -n converse -l app.kubernetes.io/name=librechat-opencode-wellknown` |
| Stale JSON served | Pod cache (shouldn't happen — `Cache-Control: no-store`) | `kubectl rollout restart deployment/librechat-opencode-wellknown -n converse` |

## Related

- ADR-0014 — the chart split + the well-known design
- ADR-0048 — the global browser plugin + closed-loop `@frontend`; removes
  `chrome-devtools`; **the per-agent tool-injection token model** (the *why*
  behind the ✅ note in *Agents & tool scoping*)
- ADR-0042 — the curated MCP catalog pushed via `config.mcp`
- ADR-0038 — the gateway `/mcp/*` routes + OAuth the remote MCPs target
- ADR-0009 — humans use Lightbridge self-service for API keys; the
  opencode CLI flow is the desktop complement
- ADR-0003 — SA-skip-OPA via `azp`; opencode tokens have
  `azp=opencode-cli` so they go through full OPA validation (humans)
- `charts/librechat-opencode-wellknown/values.yaml` — the JSON content
  source
- `charts/keycloak-baseline/values.yaml` — where the `opencode-cli`
  client + audience mapper land in a follow-up
