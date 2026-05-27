# `librechat-opencode-wellknown` — leaf

Tiny nginx serving a static JSON at
`https://ai.camer.digital/opencode/.well-known/opencode` so users can
`opencode auth login https://ai.camer.digital/opencode`.

**ADR:** [`0014`](../../docs/adr/0014-split-librechart-and-opencode-wellknown.md)
**User-facing doc:** [`docs/opencode-well-known.md`](../../docs/opencode-well-known.md)
**Orchestrator:** [`librechart`](../librechart/)

## What it renders

- `Deployment` — `nginxinc/nginx-unprivileged:1.27-alpine`, 2 replicas,
  10m / 16Mi requests. Hardened: `runAsNonRoot`,
  `readOnlyRootFilesystem`, drop ALL capabilities, seccomp
  `RuntimeDefault`, `automountServiceAccountToken: false`.
- `Service` — ClusterIP, port 80 → 8080
- `Ingress` — Traefik, exact-match `/opencode/.well-known/opencode` on
  `ai.camer.digital`, same TLS cert as LibreChat (longest-path-wins
  routing means this doesn't conflict with the `/` ingress)
- Two `ConfigMap`s:
  - `nginx-config` — custom `default.conf` with one exact-match
    location, `Content-Type: application/json`, `Cache-Control: no-store`
  - `content` — the well-known JSON itself, rendered via `toJson`
    (compact, deterministic)

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

| Key | What |
|---|---|
| `wellKnown.auth.{command, env}` | The stub argv + env name |
| `wellKnown.config.plugin` | Array of npm packages opencode auto-installs |
| `wellKnown.config.provider.<id>.options.baseURL` | OpenAI-compatible endpoint |
| `wellKnown.config.provider.<id>.options.oauth2.{issuer, clientId, scopes, authFlow}` | Keycloak OAuth config for the plugin. **Set `authFlow: device_code`** (plugin default is `authorization_code` which binds a localhost callback port and breaks headless use). |
| `image.{repository, tag, pullPolicy}` | nginx image pin |
| `replicaCount` | Defaults to 2 |
| `resources` | requests/limits |
| `ingress.{enabled, className, host, path, annotations, tls.{enabled, secretName}}` | Ingress shape |

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
