# ADR-0077: Phoenix-style chat dashboards on the AI Gateway's existing OpenInference traces

**Status:** Accepted
**Date:** 2026-07-07
**Deciders:** @stephane-segning

## Context

The request was to reproduce an Arize-Phoenix-style "what's going on with
chats" view in Grafana: one global chat overview (embeddings excluded, no
input), one per-user cut with the user list sourced from Keycloak, and
(bonus) a full single-chat drill-down.

Investigating what data is actually available turned up something
undocumented: **the AI Gateway ext-proc has been emitting full-content
OpenInference traces to Tempo all along.** `OTEL_EXPORTER_OTLP_ENDPOINT` was
already set in `charts/core-gateway/templates/gateway-config.yaml` (added for
the ext-proc's own instrumentation, not deliberately for this). Envoy AI
Gateway's ext-proc auto-instruments every OpenAI-compatible chat/embeddings
call using [OpenInference semantic conventions](https://github.com/Arize-ai/openinference/tree/main/spec)
— the same schema Phoenix itself uses — and **defaults to capturing full
request/response content** (`OPENINFERENCE_HIDE_INPUTS`/`_HIDE_OUTPUTS` are
opt-in, unset here). Confirmed live against the cluster's Tempo
(`/api/search/tags`, 2026-07-07): real spans carry
`llm.input_messages.N.message.content`, `llm.output_messages.*`,
`llm.model_name`, `llm.token_count.{prompt,completion,total}`, and
`openinference.span.kind` ∈ `{LLM, EMBEDDING}` — i.e., full prompt/response
text, per chat turn, already flowing into Tempo, unattributed to anyone.
[ADR-0002](./0002-replace-phoenix-with-tempo.md) anticipated Tempo could
cover what Phoenix did "at this scale"; this is that bet paying off, just
never verified or built on top of until now.

**The gap, and why it turned out not to matter:** spans carry no
`user.id`/`session.id`/`user.email` attribute, and the Envoy access-log JSON
(Loki's identity source, ADR-0046) carries no `trace_id` — so there is no way
to join a specific person's identity to their trace content, or to filter
Tempo by user via TraceQL. Envoy AI Gateway supports closing this natively via
a generic header→span-attribute mapping, `controller.spanRequestHeaderAttributes`
(a Helm value on the `aieg` controller app). A PR doing exactly that
(`x-oidc-user-id:user.id,x-oidc-email:user.email`, using headers Authorino
already stamps on every request) was drafted and opened in the private
`ai-helm-values` repo — then **closed** after live verification showed it
solved a problem nobody had: opening several live traces directly (raw
`input.value`/`output.value`, and every `llm.input_messages.*`/
`output_messages.*` attribute) confirmed full content was already completely
readable without any user attribute, in Phoenix's era and now — the same
OpenInference spans, unchanged, sent to both backends in parallel per
ADR-0002. No request body carries an OpenAI-style `user` field either
(checked live). So the only thing the mapping would have bought is
server-side TraceQL filtering by person — at a real, deliberate privacy cost
(making already-full-content traces directly attributable to a named person).
Not worth it for a capability nobody asked to use once it was clear content
access never depended on it.

There is still no LibreChat-conversation-level identifier anywhere in the
pipeline (LibreChat's internal Mongo `conversationId` is never forwarded past
LibreChat). Closing that would need a new forwarded header + an Authorino
pass-through rule + (per the mapping above) no further gateway changes — but
that's out of scope here; the bonus "single chat" dashboard was dropped for
this round.

## Decision

1. **Two new dashboards**, `tools/dashboards/src/dashboards/envoy_ai_gateway/{chat_overview,chats_by_user}.py`
   (ADR-0008 generator pattern), registered in `main.py` and
   `charts/observability-dashboards/values.yaml` (`folderRef: ai-gateway`):
   - **`chat-overview`** — no input variables. Loki/Mimir volume, cost,
     tokens, error rate, and P95 latency (embeddings excluded via a
     `model!~` regex built from the new `EMBEDDING_MODEL_KEYS` constant in
     `_common.py`, kept in sync with `kind: embedding` entries in
     `charts/ai-models/values.yaml`), plus a live Tempo trace-list panel
     (`type="traces"`, same panel type `scoreboard.py` already uses) scoped
     to `span.openinference.span.kind = "LLM"`. Click a trace to see the
     full prompt/response content Grafana's native span view already
     renders — no custom table/column-selection needed.
   - **`chats-by-user`** — a `$user` picker sourced from a raw-SQL Postgres
     query variable against the read-only Keycloak datasource (ADR-0063;
     `__text`/`__value` column aliases), not `label_values(email)` like
     `per_user.py`/`jwt_tokens.py`, so it lists real people independent of
     recent traffic. Loki-filtered per-user aggregates (requests, tokens,
     cost, error rate). **Deliberately no trace/content panel** — see below.
2. **Span attribution: investigated, then explicitly rejected.** The
   `controller.spanRequestHeaderAttributes` PR described above was opened in
   `ai-helm-values`, then closed unmerged once live verification showed it
   wasn't needed. Nothing in this repo depends on it.
3. **Bonus "single chat" dashboard dropped for this round** — no
   conversation-level identifier exists yet; revisit if/when LibreChat
   forwards one (a new, separate change spanning LibreChat config + an
   Authorino pass-through rule).

## Consequences

- **Good.** Two working Phoenix-style dashboards, reusing an existing,
  previously-invisible tracing capability instead of building new
  instrumentation. No new logging was added — the content was already being
  sent; these dashboards are the first thing to surface it.
- **No privacy blast-radius increase.** The span-attribution mapping was
  built, verified unnecessary, and closed before merging — Tempo's identity
  surface is unchanged from before this ADR (no `user.id`/`user.email` on any
  span). `chats-by-user` stays scoped to Loki aggregates only; reading actual
  chat content for a specific person means browsing `chat-overview`'s global
  trace feed and recognizing them from the content itself (model choice,
  writing style, task) — a real limitation, accepted deliberately rather than
  paying the privacy cost to remove it.
- **`EMBEDDING_MODEL_KEYS` is a manually-synced list** (currently just
  `qwen3-embedding-8b`) — same convention as `SERVICE_ACCOUNT_CLIENTS`. A new
  embedding model added to `charts/ai-models/values.yaml` without updating
  this constant will leak into the "chat" aggregates (the Tempo trace panel
  is unaffected — it filters on the real `openinference.span.kind`, not a
  model-name guess).
- **No prompt/response content is added to Loki/Mimir** — those stay
  metadata-only (tokens/cost/latency/model/errors), as before. All content
  visibility comes from Tempo, which already had it.
- **Single-chat drill-down remains unbuilt.** Revisiting it later needs a new
  LibreChat→gateway header (mirroring the existing `X-LibreChat-User`
  pattern) plus an Authorino pass-through rule — a bigger, separate change.

## Alternatives considered

- **Log full prompt/response into Loki (via a new Envoy access-log field).**
  Rejected: Envoy has no body-content access-log formatter, and the content
  already exists in Tempo via OpenInference — building a second, redundant
  content pipeline into Loki would be pure duplication.
- **Join Tempo traces to Loki identity via `trace_id`.** Rejected: the Envoy
  access-log JSON doesn't emit `trace_id` (only Alloy's generic pod-log stage
  does, for unrelated app logs), so this would need its own access-log field
  addition for a filtering capability that turned out not to be needed
  (see below) — not worth building.
- **Tag spans with `user.id`/`user.email` via `controller.spanRequestHeaderAttributes`.**
  Built, PR opened in `ai-helm-values`, then **closed unmerged**. Live
  verification (opening real traces, reading `input.value`/`output.value`
  and every `llm.input_messages.*`/`output_messages.*` attribute directly)
  confirmed full chat content was already completely accessible without any
  user attribute — it always had been, including in Phoenix's era, since
  both backends received the exact same spans (ADR-0002). The mapping would
  only have enabled server-side TraceQL filtering by person, at a real
  privacy cost (making already-full-content traces directly person-
  attributable) that isn't justified for a capability nobody needed.
- **Custom Tempo "spans" table panel with `| select(...)` columns and a
  content-preview field** instead of the native `type="traces"` panel.
  Rejected: `scoreboard.py` already established the native trace-list panel
  as this codebase's convention for embedding Tempo in a dashboard, it needs
  no column/truncation design, and clicking into a trace gives strictly more
  detail (the full span tree) than a flat table row would.
