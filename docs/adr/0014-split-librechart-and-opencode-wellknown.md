# ADR-0014: Split `charts/librechart` into 3 leaf charts + add opencode `.well-known`

**Status:** Accepted
**Date:** 2026-05-24
**Deciders:** @stephane-segning

## Context

`charts/librechart` was a 722-line monolith bundling four unrelated
concerns into one ArgoCD Application:

- LibreChat (the chat app — Deployment + Service + Ingress + the
  `librechat.yaml` ConfigMap)
- MongoDB (LibreChat's primary data store)
- Meilisearch (LibreChat's full-text search backend)
- A grab-bag of `rawResources` (LimitRange, ResourceQuota, HPA)

Three problems:

1. **No per-component sync isolation.** A typo in the librechat env
   block re-renders and re-applies Meilisearch and MongoDB too. Bumping
   Meilisearch re-applies LibreChat's Deployment for no reason.
2. **No per-component lifecycle.** "Pause search reindex while we
   migrate MongoDB" requires editing the monolithic values — there's
   no Application boundary to wrap.
3. **No room for additions.** A new requirement — host an opencode
   `.well-known/opencode` JSON so `opencode auth login
   https://ai.camer.digital/opencode` resolves — wants its own tiny
   nginx + ConfigMap. Bolting that into the monolith would inflate
   it further; landing it as a sibling sub-chart fits the natural
   shape.

ADR-0012 introduced the orchestrator-emits-ApplicationSet pattern for
`charts/ai-models`. Same pattern fits here at the lower granularity of
"one Application per LibreChat-adjacent component."

## Decision

Split `charts/librechart` into **four charts**:

| Chart | Role | What it renders | Sync-wave |
|---|---|---|---|
| `librechat-search` | Leaf | Meilisearch (helm dep `meilisearch@0.25.1`) | `-1` |
| `librechat-app` | Leaf | LibreChat (bjw-s `app-template@4.6.2`) + MongoDB (`mongodb@1.7.6`) + `librechat.yaml` ConfigMap | `0` |
| `librechat-opencode-wellknown` | Leaf | nginx + ConfigMap serving `https://ai.camer.digital/opencode/.well-known/opencode` | `1` |
| `librechart` | Orchestrator | One `ApplicationSet` (List generator) emitting the three child Applications | n/a (the AppSet itself, deployed by the existing `librechat` Application in `charts/apps/values.yaml`) |

The `librechat` Application entry in `charts/apps/values.yaml` is
**unchanged** — it still points at `path: charts/librechart`, which now
emits the ApplicationSet rather than the K8s resources directly.

Children carry their own values defaults in their leaf chart's
`values.yaml`. The orchestrator only flows ArgoCD wiring
(`targetRevision`, project, destination) plus the per-child sync wave.
No per-child `valuesObject` overrides today; if env-specific overrides
become a need, add a `helmValuesByChild` map to the orchestrator and
inline overrides per element.

### Why pair LibreChat with MongoDB instead of splitting them

LibreChat's runtime state lives in Mongo. Bundling them in one
Application means a single sync brings the pair up; the Application
boundary matches the operational coupling. Splitting them would let
ArgoCD bring up LibreChat against a missing/empty Mongo and report
healthy when the experience is broken. Same lifecycle ⇒ same
Application.

### Why Meilisearch is separate

Search is operationally independent — Meilisearch can be reindexed,
restarted, or temporarily down without taking LibreChat fully offline
(LibreChat degrades gracefully when search is unavailable). Different
lifecycle ⇒ different Application. Sync-wave `-1` so it's up before
LibreChat's first request reaches the search code path.

### Opencode `.well-known/opencode` — what it actually is

opencode's `.well-known/opencode` is **NOT** OIDC discovery. It's an
opencode-proprietary descriptor with two consumer shapes (verified
against `packages/opencode/src/cli/cmd/providers.ts` and
`config/config.ts`):

1. **`auth.command` / `auth.env`** — opencode spawns the argv locally
   on the user's machine; `stdout.trim()` is treated as a bearer token
   and stored in `~/.opencode/auth.json` under env-var name `env`.
2. **`config`** — inline opencode config merged at bootstrap. Carries
   `plugin`, `provider`, `mcp`, etc.

We use the `@vymalo/opencode-oauth2` plugin (vymalo's npm scope) to
handle OAuth2 inside the `config` block. The plugin's two opencode
hooks — `config` (registers/patches the provider, fetches and caches
the model list) and `chat.headers` (sets `Authorization: Bearer
<token>` per request) — obviate `auth.command` entirely.

**Plugin auto-install:** opencode reads `config.plugin` and runs
`bun install` automatically at startup, caching under
`~/.cache/opencode/node_modules/`. So shipping the plugin name in the
well-known JSON is sufficient — end users only run
`opencode auth login https://ai.camer.digital/opencode` and the plugin
arrives on first launch. No manual `opencode plugin add` or
`npm install` step. (Documented at
<https://opencode.ai/docs/plugins/>.)

**`auth.command` ships as a no-op stub.** It satisfies opencode's
auth-login schema check; opencode never uses the token because the
plugin's `chat.headers` hook overrides the Authorization header per
request from its own per-OS cache.

**Flow chosen: `device_code` (RFC 8628).** The plugin defaults to
`authorization_code` which binds a localhost callback port; that
breaks on headless or remote dev machines. `device_code` always works.

**Audience pinning** to `lightbridge-api-key` is **not** in the
opencode-oauth2 plugin's config surface for non-federated flows.
Configure via a Keycloak client-scope audience mapper on the
`opencode-cli` client. Documented as a follow-up.

### The nginx pod

Tiny (`nginxinc/nginx-unprivileged:1.27-alpine`, 10m/16Mi requests,
2 replicas). Two ConfigMaps:

- `<release>-nginx-config` — custom `default.conf` with one exact-match
  location (`= /opencode/.well-known/opencode`) that sets
  `Content-Type: application/json` and `Cache-Control: no-store`.
  Everything else returns 404 (the pod has one job).
- `<release>-content` — the well-known JSON itself, rendered from
  `.Values.wellKnown` via `toJson` (compact, deterministic) so
  YAML-vs-JSON style choices in values don't show up in the serialized
  output.

Security: `runAsNonRoot`, `readOnlyRootFilesystem`, dropped capabilities,
seccomp `RuntimeDefault`. `automountServiceAccountToken: false` — the
pod calls nothing.

## Consequences

**Positive**
- Per-component ArgoCD Applications with their own sync status,
  health, and rollback UI. Operating one component is one Application
  edit.
- Failure isolation: a malformed `librechat.yaml` config breaks only
  `librechat-app`; `librechat-search` keeps running and the opencode
  well-known stays served.
- The `.well-known/opencode` endpoint is now a tiny independent app
  with its own lifecycle. Adding more static-JSON endpoints (other
  CLIs, MCP discovery JSON, etc.) becomes "drop another sub-chart"
  not "bolt onto LibreChat."
- Audit fix: pre-split Chart.yaml had `name: chat` vs directory
  `librechart`. Aligned to `name: librechart`.
- Audit fix: pre-split `pdb.yaml` hardcoded
  `app.kubernetes.io/instance: librechat`; now uses `{{ .Release.Name }}`.

**Negative**
- More moving parts. Four charts where there was one.
  ApplicationSet templating quirks (the `{{ "{{ .field }}" }}` literal
  escape, `goTemplate: true`) carry over from ADR-0012.
- `helm template charts/librechart` shows an ApplicationSet, not the
  underlying K8s resources. To verify a leaf's output, template the
  leaf directly: `helm template librechat-app charts/librechat-app`.
- Two-layer rendering during ArgoCD reconcile: parent App → AppSet
  → child Apps → leaf charts. Slower first-sync; subsequent syncs
  unchanged.
- `targetRevision` on the orchestrator points at the branch
  (`claude/magical-bohr-390242`) during this PR; **must flip to `main`
  on merge.** TODO'd in the orchestrator's `values.yaml` comments.

**Neutral / follow-ups**
- The RAG API (`rag-api` block in librechat-app values) is
  `enabled: false`. If/when re-enabled, consider splitting it into a
  fourth `librechat-rag` leaf. Today it stays bundled with librechat-app.
- Keycloak `opencode-cli` client + audience mapper for
  `lightbridge-api-key` is a separate Keycloak-realm config task.
- If we want the well-known JSON to be authenticated (so the model
  catalog doesn't leak publicly), switch to opencode's
  `config.remote_config` shape with a second URL behind auth. Today
  it's inline + public.

## Alternatives considered

- **Status quo (one chart).** Works; the three problems above remain.
  Rejected.
- **Helm `dependencies:` composition only (parent → 3 sub-charts).**
  Same Application boundary; no per-component sync isolation.
  Rejected — this was effectively the pre-split shape.
- **Bolt the well-known nginx into librechat-app**. Saves one
  Application but couples a static-JSON endpoint to LibreChat's
  release lifecycle. Rejected; the operational coupling doesn't
  warrant the configurational coupling.
- **Build `auth.command` to do something real** (device-code flow
  via a small Go/Python helper user installs). Rejected: the
  @vymalo/opencode-oauth2 plugin obviates it; the no-op stub
  satisfies opencode's schema with zero engineering cost.
- **Use `config.remote_config` instead of inlining the config.**
  Lets the model catalog and provider block live behind auth.
  Considered; deferred until there's a real reason to gate the
  catalog (today the same info is visible from `models.json` on the
  gateway anyway).

## Migration verification

`helm template charts/librechat-search`, `helm template
charts/librechat-app`, `helm template charts/librechat-opencode-wellknown`
each render cleanly. The orchestrator emits an `ApplicationSet` with
three list elements pointing at those paths. `helm template
charts/apps` (the umbrella) is unaffected — the `librechat` Application
entry still references `charts/librechart`.

Cluster-side rollover: the pre-split LibreChat / Mongo / Meilisearch
resources get re-adopted by the new child Applications via ArgoCD's
tracking labels. Coordinate the first sync with a brief pause to
avoid duplicate ownership in flight (same caveat as ADR-0012's
ai-models split).

## Related

- ADR-0012 — `ai-models` split (same orchestrator-emits-ApplicationSet
  pattern at a different granularity)
- ADR-0009 — humans use the Lightbridge self-service portal for API
  keys; opencode's plugin-driven OAuth flow is the desktop-CLI
  complement
- New doc: `docs/opencode-well-known.md` (the how — admin recipe,
  Keycloak `opencode-cli` client setup, plugin install instructions
  for end-users, troubleshooting)

## Related files

- `charts/librechart/` — orchestrator (Chart.yaml + values.yaml +
  ApplicationSet template)
- `charts/librechat-app/` — LibreChat + MongoDB leaf
- `charts/librechat-search/` — Meilisearch leaf
- `charts/librechat-opencode-wellknown/` — nginx + ConfigMap leaf
- `charts/apps/values.yaml` — `librechat` Application entry unchanged
