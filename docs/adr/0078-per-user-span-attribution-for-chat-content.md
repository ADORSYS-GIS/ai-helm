# ADR-0078: Adopt per-user span attribution for chat content

**Status:** Accepted
**Date:** 2026-07-07
**Deciders:** @stephane-segning
**Supersedes:** the "reject span attribution" decision in [ADR-0077](./0077-phoenix-style-chat-dashboards.md)

## Context

[ADR-0077](./0077-phoenix-style-chat-dashboards.md) built two Phoenix-style
chat dashboards and, in its Alternatives Considered, **rejected** tagging the
AI Gateway's OpenInference spans with user identity — reasoning that full chat
content was already readable in Tempo without it, so the
`controller.spanRequestHeaderAttributes` mapping (opened as a PR in
`ai-helm-values`, then closed) was unnecessary.

That reasoning was **half right and misleadingly framed**. It is true for the
*global* `chat-overview` board: content is fully present on every span, no
attribution needed. But it is **wrong for the per-user requirement**. Verified
directly against a live LLM span (2026-07-07), the complete non-content
attribute set is:

```
input.mime_type, input.value, output.mime_type, output.value,
llm.model_name, llm.system, llm.invocation_parameters,
llm.token_count.*, openinference.span.kind
```

— full conversation content, but **no user identity, no `x-request-id`, no
`trace_id`, and resource attributes limited to `service.name` +
`telemetry.sdk.*`**. So a span cannot be attributed to a person, and there is
**no correlation key to join it to the Loki access logs** (which *do* carry
`user_id`/`email` labels but carry no `trace_id`, and the span carries no
request-id). The two datasets are disjoint. Therefore per-user chat *content*
is impossible without stamping identity onto the span — and
`spanRequestHeaderAttributes` is the only mechanism that does so.

ADR-0077 conflated "global content works without attribution" with "per-user
content is impossible," presenting a deliberate *choice* (skip attribution) as
a hard *limit*. The maintainer's requirement #2 — "chats **by user**" — needs
the content, not just metadata. Hence this reversal.

## Decision

**Adopt the span-attribution mapping.** In `ai-helm-values`
`environments/prod/values/aieg.yaml`:

```yaml
controller:
  spanRequestHeaderAttributes: "x-oidc-user-id:user.id,x-oidc-email:user.email"
```

- The key is confirmed present in **ai-gateway-helm v1.0.0** (the version we
  run): `controller.spanRequestHeaderAttributes` in the chart `values.yaml`,
  rendered to a `--spanRequestHeaderAttributes=` controller arg in
  `templates/deployment.yaml` **only when set** (which is why the live v1.0.0
  controller shows no such flag today). Not a fabricated/newer key.
- Maps the Keycloak identity headers Authorino already stamps on every request
  (`x-oidc-user-id`, `x-oidc-email` — ADR-0011/0021; present at ext-proc time,
  they appear in the Envoy access log) onto the ext-proc's OpenInference spans
  as `user.id` / `user.email`. No new header plumbing.
- Applies to **newly-created ext-proc pods** — takes effect as pods roll after
  the controller reconciles the new arg.

The `chats-by-user` dashboard (`tools/dashboards/.../chats_by_user.py`) gains a
Tempo trace panel filtered by `span.user.email = "$user"` (the `$user`
variable's value is the Keycloak email, matching what the mapping stamps),
alongside the per-request Loki metadata log. `chat-overview` is unchanged.

## Consequences

- **Per-user chat content works** — requirement #2 delivered. Pick a person,
  read their actual conversations.
- **Privacy blast radius increases — deliberately.** Full chat content already
  existed in Tempo, readable by anyone with Tempo/Grafana access but keyed only
  by an opaque trace id. Adding `user.id`/`user.email` makes every future trace
  **directly attributable to a named person** via the `chats-by-user` dashboard
  or a direct Tempo query. This is the exact tradeoff ADR-0077 flagged and
  declined; it is now accepted as the cost of the per-user feature. Reviewed as
  its own `ai-helm-values` PR (continuous-delivery repo, merge = live deploy),
  separate from the dashboard change.
- **`chats-by-user`'s trace panel is "No data" until the values change
  deploys** and ext-proc pods roll; its Loki metadata log works immediately.
- **Only new traffic is attributed** — spans emitted before the rollout keep no
  identity (forward-only, like every other attribution here).
- **Retroactive rollback** = revert the `ai-helm-values` change; new spans stop
  carrying identity. Already-emitted attributed spans age out with Tempo
  retention.

## Alternatives considered

- **Keep ADR-0077's metadata-only `chats-by-user`.** Rejected: it doesn't meet
  the "chats by user" requirement (the maintainer explicitly wants the content,
  having seen it's all present in the spans).
- **Join Loki (has user) to Tempo (has content) at query time.** Rejected as
  impossible: verified the span carries no `x-request-id`/`trace_id` and the
  access log carries no `trace_id`, so there is no shared key to join on. Even
  a Grafana data-link would have nothing to pass.
- **Infer the user from span content** (system prompt fingerprint, embedded
  client URIs like Zed's `zed:///agent/thread/...`). Rejected: unreliable,
  client-specific, and identifies a conversation/tool at best, not a person.
- **Stamp `session.id` too** (the mapping's documented default is
  `agent-session-id:session.id`) for a per-conversation view. Deferred: nothing
  is confirmed to send a usable session/thread header today; revisit for the
  still-unbuilt single-chat drill-down (ADR-0077 §"Not built").
