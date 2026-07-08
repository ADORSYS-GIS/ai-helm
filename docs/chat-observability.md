# Phoenix-style chat observability (OpenInference traces in Tempo)

**Status:** live. **ADRs:** [0077](./adr/0077-phoenix-style-chat-dashboards.md)
(the dashboards) + [0079](./adr/0079-per-user-span-attribution-not-viable.md)
(per-user content is *not* achievable — the AIEG ext-proc runs before Authorino;
supersedes [0078](./adr/0078-per-user-span-attribution-for-chat-content.md)).
**Dashboards:** `AI Gateway — chat overview` (uid `envoy-ai-gateway-chat-overview`),
`AI Gateway — chats by user` (uid `envoy-ai-gateway-chats-by-user`).

The cost/consumption boards ([`cost-observability.md`](./cost-observability.md),
[`per-user-observability.md`](./per-user-observability.md),
[`jwt-token-observability.md`](./jwt-token-observability.md)) answer "who spent
what". This pair answers Arize-Phoenix's question instead: **what did the
conversation actually say** — the request/response content, per chat turn.

## Where the content comes from

The AI Gateway ext-proc auto-instruments every OpenAI-compatible chat/
embeddings call using [OpenInference semantic conventions](https://github.com/Arize-ai/openinference/tree/main/spec)
(the same schema Phoenix itself uses) whenever it has an OTLP endpoint —
which it has had since `charts/core-gateway/templates/gateway-config.yaml`
set `OTEL_EXPORTER_OTLP_ENDPOINT` (added for the ext-proc's own
instrumentation, not deliberately for this). OpenInference **defaults to
capturing full request/response content**
(`OPENINFERENCE_HIDE_INPUTS`/`_HIDE_OUTPUTS` are opt-in, unset here). This
means Tempo has been holding full-content chat traces all along — confirmed
live against the cluster (`/api/search/tags`, `/api/traces/<id>`, 2026-07-07):

| Attribute | Holds |
|---|---|
| `openinference.span.kind` | `LLM` or `EMBEDDING` — the chat/embedding split |
| `llm.input_messages.N.message.{role,content}` | each input message, per turn |
| `llm.output_messages.N.message.{role,content}` | each output message |
| `input.value` / `output.value` | full raw request/response JSON |
| `llm.model_name` | requested model |
| `llm.token_count.{prompt,completion,total}` | token usage for the span |

No new logging was added to get this — these dashboards are the first thing
to surface a capability that was already running. This was also true in
Phoenix's era: both backends received the exact same OpenInference spans in
parallel (ADR-0002), so nothing about content access changed when Tempo
replaced Phoenix.

## Per-user identity on spans — not achievable (ADR-0079)

Spans carry **no `user.id`/`user.email`**, and the Envoy access-log JSON
(Loki's identity source, [ADR-0046](./adr/0046-per-user-attribution-otlp-envelope-repair.md))
carries no `trace_id` — and a live span carries no `x-request-id` either. So
there is **no way to attribute a span to a person and no shared key to join it
to the user-bearing Loki logs**; the two datasets are disjoint.

[ADR-0078](./adr/0078-per-user-span-attribution-for-chat-content.md) tried to
close this with the AI Gateway controller's `spanRequestHeaderAttributes`
mapping (`x-oidc-user-id:user.id,x-oidc-email:user.email`), tagging spans with
the Keycloak identity Authorino stamps. **It was deployed end-to-end and
produced nothing.** [ADR-0079](./adr/0079-per-user-span-attribution-not-viable.md)
found and confirmed why, by pulling the live Envoy filter chain
(`config_dump`, external `api-https` listener):

```
1.  ext_proc/aigateway        ← AI Gateway ext-proc (BUILDS the span)  ⟵ FIRST
    …
7.  ext_authz/…kuadrant-policies-main   ← Authorino (INJECTS x-oidc-*)
```

The AIEG ext-proc is **HTTP filter #1 — before Authorino** (it must inspect the
raw body to extract the model before routing). So it captures request headers
for the span *before* `x-oidc-*` exist. The access log sees them only because
`%REQ(...)%` reads the *final* header state. The `filterOrder` reorder (move
`ext_proc` after `ext_authz`) was **declined** — a global reorder on the prod
gateway affecting LLM *and* MCP routes, with a suffixed filter name and
routing/transform risk, isn't worth a per-user convenience.

**Bottom line:** per-user chat *content* is a confirmed structural limit. The
`spanRequestHeaderAttributes` config was reverted (it was a no-op). To read a
specific person's content, browse the global `chat-overview` trace feed and
recognise them from the content. **No privacy change** — nothing was ever
attributed.

## The two dashboards

- **`chat-overview`** — no input. Loki/Mimir volume/cost/tokens/error-rate/
  latency (embeddings excluded via a `model!~` regex, see
  `EMBEDDING_MODEL_KEYS` in `tools/dashboards/src/dashboards/_common.py` —
  keep in sync with `kind: embedding` entries in `charts/ai-models/values.yaml`),
  plus a live Tempo trace-list panel (Grafana's native `type="traces"` panel,
  the same one `scoreboard.py` already uses) scoped to
  `{ resource.service.name = "core-gateway" && span.openinference.span.kind = "LLM" }`.
  Click a trace to see the full prompt/response — Grafana's built-in
  span-detail view already renders the OpenInference attributes above, no
  custom table needed.
- **`chats-by-user`** — a `$user` picker sourced from a raw-SQL query
  variable against the read-only Keycloak Postgres datasource
  ([ADR-0063](./adr/0063-grafana-readonly-keycloak-datasource.md); `__text`/
  `__value` column aliases), so it lists real people independent of recent
  traffic — not `label_values(email)` like `per_user.py`/`jwt_tokens.py`.
  ⚠️ **Postgres template-variable gotcha:** the variable's `query` must be a
  **plain SQL string**, NOT the `{rawSql, format: table, …}` object a panel
  target uses. Grafana's *variable* resolver only honors `format: table` for a
  string query (it routes through `metricFindQuery`, which forces table); given
  an object it ignores the stored format and runs `time_series`, which fails on
  a SQL with no time column → the UI shows *"error when executing the sql
  query"*. Verified live in Grafana 12.3 (string form resolved `__text`/
  `__value`; both object forms errored). This is the **opposite** of a panel
  target — don't "fix" it into an object. The hero is a **per-request Loki log**
  (one row per chat: model/status/tokens/cost/latency, `email="$user"`) —
  distinct from the `per_user`/`actor-consumption` rollup charts. Metadata only;
  per-user content isn't filterable (ADR-0079, above).

⚠️ **No raw user input is ever interpolated into SQL.** The `$user` variable's
*available options* come from a static-realm-id query; the *selected* value
only ever reaches a Loki label matcher — never a second SQL string — so
there's no SQL-injection surface from a manipulated `?var-user=` URL param.

## Not built: single-chat drill-down

There is still no LibreChat-conversation-level identifier anywhere in the
pipeline — LibreChat's internal Mongo `conversationId` is never forwarded
past LibreChat's own backend. A true "pick one chat, see its full turn-by-turn
trace" dashboard needs a new forwarded header (mirroring the existing
`X-LibreChat-User` pattern in `charts/librechat-app/values.yaml`) plus an
Authorino pass-through rule — out of scope for ADR-0077, revisit if wanted.

## Verify

```bash
export KUBECONFIG=/Users/selast/dev/personal/hetzner-k8s/kubeconfig
kubectl port-forward -n observability svc/tempo 3200:3200 &
curl -s "http://localhost:3200/api/search/tag/openinference.span.kind/values"
# {"tagValues":["EMBEDDING","LLM"]}
curl -s "http://localhost:3200/api/search/tag/user.email/values"
# empty — and stays empty (ADR-0079): the AIEG ext-proc runs before Authorino,
# so its spans never get the x-oidc-* identity. Confirmed by pulling the live
# filter chain (config_dump on the api-https listener: ext_proc/aigateway is
# filter #1, ext_authz is #7).

# Read content on any trace (works regardless of attribution):
curl -s "http://localhost:3200/api/search?q=%7B%20span.openinference.span.kind%20%3D%20%22LLM%22%20%7D&limit=1" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['traces'][0]['traceID'])"
# then GET /api/traces/<id> and inspect the input.value / llm.input_messages.* attributes
```
