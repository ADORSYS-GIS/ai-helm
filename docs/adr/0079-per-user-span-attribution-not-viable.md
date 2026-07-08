# ADR-0079: Per-user span attribution is not viable — the AIEG ext-proc runs before Authorino

**Status:** Accepted
**Date:** 2026-07-08
**Deciders:** @stephane-segning
**Supersedes:** [ADR-0078](./0078-per-user-span-attribution-for-chat-content.md)

## Context

[ADR-0078](./0078-per-user-span-attribution-for-chat-content.md) adopted the AI
Gateway controller's `spanRequestHeaderAttributes` mapping
(`x-oidc-user-id:user.id,x-oidc-email:user.email`) to stamp Keycloak identity
onto the ext-proc's OpenInference spans, so `chats-by-user` could filter Tempo
by person and show per-user chat **content**. It was deployed end-to-end and
verified live. **It produced nothing** — spans still carried no `user.id`/
`user.email` after a full gateway roll.

Root cause, confirmed by pulling the live Envoy filter chain
(`config_dump?resource=dynamic_listeners`, external `api-https` listener,
2026-07-08):

```
1.  ext_proc/aigateway        ← AI Gateway ext-proc (BUILDS the span)  ⟵ FIRST
    …MCP oauth-metadata custom_response filters…
7.  ext_authz/…kuadrant-policies-main   ← Authorino (INJECTS x-oidc-*)
8.  jwt_authn
9.  rbac
10. ratelimit
…
13. router
```

**The AIEG ext-proc is HTTP filter #1 — six positions before Authorino.** It
captures the request headers for the span at the very start of the chain,
*before* Authorino injects `x-oidc-user-id`/`x-oidc-email`. So the mapping has
nothing to read. (The access log shows the headers because `%REQ(...)%` reads
the *final* request-header state, after Authorino; the ext-proc reads them at
filter #1.) This was corroborated behaviourally first: CI requests carrying
populated `x-oidc-*` headers (proven in the access log) still produced spans
with neither attribute.

AIEG places its ext-proc first **by design** — it must inspect the raw request
body to extract the model and translate the OpenAI request before routing.

## Decision

**Abandon per-user span attribution. Accept metadata-only `chats-by-user`.**

- **Revert** the `ai-helm-values` `controller.spanRequestHeaderAttributes` (it
  is a confirmed no-op given the filter order; leaving it is dead config).
- **Remove** the Tempo trace panel from `chats-by-user` (it would be permanently
  "No data"). The dashboard keeps its Keycloak-sourced `$user` picker, per-user
  stat row, and the **per-request Loki metadata log** (model/status/tokens/cost/
  latency) — which works and is distinct from the per_user/actor-consumption
  rollup charts.
- **Global `chat-overview` is unchanged** — its trace feed shows full chat
  content (unattributed), which is where content reading happens.

## Consequences

- **Per-user chat content is not available**, and this is now a *confirmed
  structural* limitation rather than an unexplored option. Reading a specific
  person's content means browsing `chat-overview`'s global feed and recognising
  them from the content — accepted.
- **No privacy change** — nothing was ever attributed (the mapping produced no
  data), so reverting it removes only dead config; Tempo's identity surface is
  unchanged from before ADR-0078.
- The `filterOrder` EnvoyProxy escape hatch (force `ext_proc` after `ext_authz`)
  was **considered and declined** — see Alternatives.

## Alternatives considered

- **Reorder filters via EnvoyProxy `filterOrder`** (`ext_proc` after
  `ext_authz`). Declined: it's a **global** reorder on the production gateway
  affecting LLM *and* MCP routes (ADR-0038/0040); the AIEG filter is a suffixed
  name (`envoy.filters.http.ext_proc/aigateway`) whose match against EG's
  `filterOrder` (bare `envoy.filters.http.ext_proc`) is unverified; per-route
  chains already order it differently; and AIEG runs it first deliberately (body/
  model parsing), so moving it after auth risks routing/transform breakage. The
  blast radius (auth, routing, MCP on live traffic) outweighs a per-user
  convenience feature. Revisit only with an upstream confirmation that it's
  safe + supported, on a canary.
- **Ask upstream / file an AIEG issue** on whether `spanRequestHeaderAttributes`
  is meant to work with ext_authz-injected headers. Reasonable future step; not
  blocking the revert.
- **Join Loki (has user) to Tempo (has content).** Still impossible — the span
  carries no `x-request-id`/`trace_id` and the access log carries no `trace_id`,
  so there is no shared key (established in ADR-0077/0078).
