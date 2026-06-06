# `librechat-opencode-wellknown` — leaf

Tiny nginx serving a static JSON at
`https://ai.camer.digital/opencode/.well-known/opencode` so users can
`opencode auth login https://ai.camer.digital/opencode`.

**ADR:** [`0014`](../../docs/adr/0014-split-librechart-and-opencode-wellknown.md)
**User-facing doc:** [`docs/opencode-well-known.md`](../../docs/opencode-well-known.md)
**Orchestrator:** [`librechart`](../librechart/)

## What it renders

The Deployment, Service, and Ingress come from
[`bjw-s app-template` v4.6.2](https://bjw-s-labs.github.io/helm-charts/docs/app-template/)
(aliased as `opencode-wellknown` in `Chart.yaml`). The two ConfigMaps
are emitted by this chart's own `templates/configmap.yaml` because their
content is computed from `.Values.wellKnown` at Helm-render time —
app-template's `configMaps:` block expects static string data.

- `Deployment` (app-template) — `nginxinc/nginx-unprivileged:1.27-alpine`,
  2 replicas, 10m / 16Mi requests. Hardened: `runAsNonRoot`,
  `readOnlyRootFilesystem`, drop ALL capabilities, seccomp
  `RuntimeDefault`, `automountServiceAccountToken: false`. ConfigMaps
  + scratch dirs come in via the `persistence:` block.
- `Service` (app-template) — ClusterIP, port 80 → 8080
- `Ingress` (app-template) — Traefik, exact-match
  `/opencode/.well-known/opencode` on `ai.camer.digital`, same TLS cert
  as LibreChat (longest-path-wins routing means this doesn't conflict
  with the `/` ingress)
- Two `ConfigMap`s (this chart's `templates/configmap.yaml`):
  - `nginx-config` — custom `default.conf` with one exact-match
    location, `Content-Type: application/json`, `Cache-Control: no-store`
  - `content` — the well-known JSON itself, rendered via `toJson`
    (compact, deterministic) from `.Values.wellKnown`

## The contract

**opencode's `.well-known/opencode` is NOT OIDC discovery.** It's
opencode-proprietary with two consumer shapes:

```jsonc
{
  "auth": {
    "command": ["…argv…"],   // spawned locally by opencode; stdout = bearer
    "env": "OPENAI_API_KEY"  // env-var name to store the token under
  },
  "config": {                // inline opencode config merged at bootstrap
    "$schema": "https://opencode.ai/config.json",
    "plugin": ["@vymalo/opencode-oauth2"],
    "provider": { "…": "…" }
  }
}
```

We ship `auth.command` as a **no-op stub** (`sh -c 'echo plugin-managed'`)
to satisfy the schema; the actual OAuth flow is handled by the
`@vymalo/opencode-oauth2` plugin loaded via `config.plugin`. opencode
auto-installs the plugin on first run (bun-install at startup; cached
under `~/.cache/opencode/node_modules/`).

## Values

The `wellKnown:` block lives at the **root** of `values.yaml` (read by
`templates/configmap.yaml`). The Deployment / Service / Ingress knobs
live under the `opencode-wellknown:` sub-chart alias (bjw-s
app-template's standard schema).

| Key | What |
|---|---|
| `wellKnown.auth.{command, env}` | The stub argv + env name |
| `wellKnown.config.plugin` | Array of npm packages opencode auto-installs |
| `wellKnown.config.provider.<id>.options.baseURL` | OpenAI-compatible endpoint |
| `wellKnown.config.provider.<id>.options.oauth2.{issuer, clientId, scopes, authFlow}` | Keycloak OAuth config for the plugin. **Set `authFlow: device_code`** (plugin default is `authorization_code` which binds a localhost callback port and breaks headless use). |
| `opencode-wellknown.controllers.main.containers.nginx.image.{repository, tag, pullPolicy}` | nginx image pin |
| `opencode-wellknown.controllers.main.replicas` | Defaults to 2 |
| `opencode-wellknown.controllers.main.containers.nginx.resources` | requests/limits |
| `opencode-wellknown.ingress.main` | bjw-s `ingress.<name>` shape (className, hosts, tls, annotations) |

## Cluster prerequisites (out of scope; see `docs/opencode-well-known.md`)

1. Keycloak `opencode-cli` public client with device-grant enabled +
   `offline_access` default scope.
2. Keycloak realm client-scope audience mapper to put
   `lightbridge-api-key` in the `aud` claim.

## Verifying

```bash
helm template librechat-opencode-wellknown . -n converse | grep -E "^kind:"
# → ConfigMap × 2, Deployment, Service, Ingress
```

Once deployed:

```bash
curl -fsSL https://ai.camer.digital/opencode/.well-known/opencode | jq
# → {"auth":{...},"config":{...}}
# Content-Type: application/json
```
