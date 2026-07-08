# ADR-0076: Remove the Grafana LLM assistant (no viable OSS use-case)

**Status:** Accepted
**Date:** 2026-06-29
**Deciders:** @stephane-segning
**Supersedes:** [ADR-0062](./0062-grafana-llm-assistant-via-internal-gateway.md)

## Context

[ADR-0062](./0062-grafana-llm-assistant-via-internal-gateway.md) wired the
`grafana-llm-app` plugin to our internal Envoy AI Gateway so in-Grafana AI would
run through our governed, cost-attributed gateway. The backend was made to work
**end-to-end** — after fixing two live bugs (the plugin needs `provider: custom`,
not `openai`, or it ignores `openAI.url` and calls `api.openai.com`; and the
Cilium egress must allow the gateway's backend port `:10443`, not the Service
port `:443`) plus a one-off Authorino re-index, a chat completion (`base`→
`gemma-4`) through the gateway returned `200` and the plugin health check passed.

But verifying it surfaced the real problem: **`grafana-llm-app` is only an LLM
*backend/proxy* — it is not a chat UI.** Self-hosted **OSS** Grafana ships no
built-in AI chat; the conversational **Grafana Assistant** is **Cloud-only**
(`grafana-assistant-app`). The other OSS consumer, "Explain Flame Graph," needs
Pyroscope profiling data we don't collect. So the working backend had **no
user-facing consumer** in our Grafana.

The only OSS path to an in-Grafana chat box is a community app
([`vikshana-graft-app`](https://github.com/vikshana/vikshana-graft-app)) that
uses `grafana-llm-app` as its backend — but it is an **unsigned, third-party
(AGPL) plugin** requiring `GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS`, able to
read all observability data and execute tools. We declined that on security
grounds (keep the plugin trust boundary tight). See the closing note on
[ai-helm#418](https://github.com/ADORSYS-GIS/ai-helm/issues/418).

## Decision

**Remove the Grafana LLM assistant entirely.** Do not keep the backend as latent
infrastructure with no consumer. Concretely, from `ai-helm-values`:

- `environments/prod/values/grafana.yaml` — drop `plugins: [grafana-llm-app]`,
  the `GRAFANA_LLM_GATEWAY_KEY` `envValueFrom`, the LLM provisioning
  `extraConfigmapMounts` + its `extraObjects` ConfigMap.
- `environments/base/deps/grafana/externalsecret-llm-key.yaml` — deleted
  (the `grafana-llm-gateway-key` gateway bearer, observability ns).
- `environments/base/deps/security-policies/external-secret.yaml` — drop the
  `internal-key-grafana` Authorino apiKey ExternalSecret.
- `environments/prod/deps/grafana/ciliumnetworkpolicy.yaml` — drop the
  `envoy-gateway-system:10443` egress allow.
- The `grafana-llm-gateway-key` store patch in the prod grafana kustomization.

**Retained (do NOT remove):** the `grafana-internal-ca` Certificate and its
`extraSecretMounts` mount at `/etc/ssl/certs/internal-gateway-ca.pem`. Introduced
by ADR-0062, it was **repurposed by [ADR-0070](./0070-ratelimit-quota-observability.md)**
as the CA-trust bundle the Grafana `Redis` datasource uses to verify redis-ha's
internal TLS. The cert + mount stay; their comments were repointed from the LLM
plugin to the Redis datasource.

The ssegning-aws property `grafana_llm_gateway_key` becomes unused (harmless; can
be deleted out-of-band at leisure). No new gateway model spend under
`x-account-id=internal-key-grafana`.

## Consequences

- **Good.** No unused, unconsumed plugin/backend; no unsigned third-party plugin;
  the plugin trust boundary stays tight; less config to carry.
- **The intent of ADR-0062/#418 is unmet in-product** — there is no in-Grafana AI
  assistant. This is accepted: it is not achievable on OSS Grafana without either
  Grafana Cloud or an unsigned plugin.
- **Live cleanup on sync:** ArgoCD prunes the LLM provisioning ConfigMap +
  ExternalSecrets; a Grafana pod roll drops the plugin (re-downloaded per start,
  so nothing lingers). Authorino still holds the now-orphaned `internal-key-grafana`
  in memory until its next restart — harmless (the Secret is pruned).
- **The two hard-won gotchas remain documented in ADR-0062's (superseded) body**
  in case a future consumer resurrects the backend: `provider: custom`, and the
  Cilium backend-port (`:10443`) rule.

## Future options (not decided here)

If in-Grafana / AI-over-observability is wanted later, the better fit is
**`mcp-grafana`** — Grafana's MCP server behind our gateway, queried from our
existing MCP clients (opencode/Claude) — which reuses our MCP + gateway pattern
(ADR-0038/0040) and needs no unsigned plugin. A **signed** Grafana chat app, if
one reaches the catalog, could reuse this same backend. Both are separate tickets.
