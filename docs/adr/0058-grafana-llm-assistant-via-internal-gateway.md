# ADR-0058: Grafana AI assistant (grafana-llm-app) on our internal AI-gateway plane

**Status:** Accepted
**Date:** 2026-06-24
**Deciders:** @stephane-segning
**Builds on:** [ADR-0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md), [ADR-0023](./0023-grafana-stateless-no-pvc.md), [ADR-0056](./0056-workload-values-in-ai-helm-values.md)

## Context

We want in-Grafana AI assistance (panel explanations, query/alert generation,
the assistant chat) for operators, but with **all** model traffic flowing
through our own Envoy AI Gateway rather than an external provider — so the same
governance and **per-account cost attribution** (ADR-0021) apply as to every
other LLM consumer. The vehicle is Grafana's official **`grafana-llm-app`**
plugin, which fronts an OpenAI-compatible backend for the AI features and sends
a static `Authorization: Bearer <key>`.

Two hard constraints shaped the design:

1. **Auth model.** Our gateway is dual-plane (ADR-0021). The *external* host
   `api.ai.camer.digital` requires a **short-lived Keycloak JWT** — incompatible
   with a plugin that only holds a *static* bearer. The *internal* plane
   (`core-gateway-internal.envoy-gateway-system.svc`) accepts a **static apiKey**
   (a Secret labeled `kuadrant.io/apikey-for=internal-gateway`) — exactly the
   long-running-service pattern LibreChat already uses. Grafana runs in-cluster,
   so the internal plane fits.
2. **Statelessness.** Grafana is stateless (emptyDir, ADR-0023) — every pod roll
   wipes click-ops config. The assistant therefore **must** be declarative.

Friction points: the internal listener is **HTTPS, signed by the internal
`self-signed-ca`**, so the plugin's Go HTTP client must trust that CA without
losing public roots (Keycloak OAuth, the grafana.com plugin catalog); and the
observability namespace is under a **Cilium default-deny-egress** baseline, so a
cross-namespace call to the gateway needs an explicit allow.

## Decision

Enable `grafana-llm-app` and point it at the **internal** gateway plane, entirely
declaratively. Per the ai-helm / ai-helm-values split (ADR-0056), the Grafana
chart is upstream and config-only, so **all of this lives in `ai-helm-values`**;
this repo carries only the decision (this ADR) + docs.

- **Provider config** (`environments/prod/values/grafana.yaml`): install the
  plugin via `plugins: [grafana-llm-app]` and ship its provisioning file as a
  ConfigMap (`extraObjects`) mounted at `/etc/grafana/provisioning/plugins/`
  (the chart has no native `apps:` key). The custom OpenAI provider points at
  `https://core-gateway-internal.envoy-gateway-system.svc.cluster.local` +
  `apiPath: /v1`; the plugin's abstract `base`/`large` slots map to real gateway
  model ids (`gemma-4` / `glm-5`).
- **Dedicated key + cost attribution.** A **distinct** internal-plane apiKey
  (Secret `internal-key-grafana` in `converse-gateway`, sourced from the new
  ssegning-aws property `grafana_llm_gateway_key`) — *not* a reuse of LibreChat's
  value — so Authorino resolves a deterministic `x-account-id = internal-key-grafana`
  bucket (the apiKey selector matches by value; a shared value would attribute
  nondeterministically). The same value is mirrored into the `observability`
  namespace (`grafana-llm-gateway-key`) and injected as `GRAFANA_LLM_GATEWAY_KEY`.
- **TLS trust.** A throwaway `self-signed-ca` leaf Certificate
  (`grafana-internal-ca`) provides the CA `ca.crt`, mounted into
  `/etc/ssl/certs/internal-gateway-ca.pem`. Go appends certs found in
  `/etc/ssl/certs`, so the internal CA is trusted **and** public roots are kept.
- **Network.** The grafana Cilium policy gains an egress allow to
  `envoy-gateway-system:443`.
- **Resilience.** `GRAFANA_LLM_GATEWAY_KEY` is `optional: true` so a not-yet-synced
  key degrades the assistant only — Grafana (critical observability) still starts.

These attach via the existing umbrella/deps mechanism (ADR-0018): the new CRs
sit in `environments/{base,prod}/deps/grafana/` and `…/deps/security-policies/`.

## Consequences

**Good.** In-Grafana AI runs through our governed, metered gateway with its own
named spend bucket; config is fully declarative and survives pod rolls; the
design reuses the established internal-plane + internal-CA-trust + deny-egress
patterns (LibreChat, eg) rather than inventing new ones.

**Trade-offs / caveats.**
- **Out-of-band prerequisite (values-repo-first).** The ssegning-aws property
  `grafana_llm_gateway_key` must exist before the values change syncs, else both
  ExternalSecrets sit in `SecretSyncedError`. Because env vars bind at pod start,
  the Grafana pod must be re-rolled once the key first lands.
- **Internal tier is uncapped/burst-only** (ADR-0021): a named bucket gives
  attribution/visibility, not a hard monthly budget, for internal callers.
- Grafana's `grafana-llm-app` MCP integration (grafana/mcp-grafana) and the
  ai-marketplace are **explicitly out of scope** — a separate follow-up.

## Alternatives considered

- **External public plane + static key** — rejected: the public host requires a
  Keycloak JWT (expires); a static long-lived token is not issuable/safe.
- **Reuse LibreChat's `converse_openai_api_key`** — rejected: a shared apiKey
  value makes Authorino's account attribution nondeterministic, collapsing
  Grafana's spend into LibreChat's bucket.
- **Container-wide `SSL_CERT_FILE` to the internal CA** — rejected: it would
  *replace* the system trust pool, breaking Keycloak OAuth and plugin downloads.
  Appending a file under `/etc/ssl/certs` preserves public roots.
- **Cluster-wide / external LLM provider** — rejected: defeats the governance +
  cost-attribution intent of the ticket.
