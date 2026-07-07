# Phoenix-style chat observability (OpenInference traces in Tempo)

**Status:** live for `chat-overview`; `chats-by-user`'s per-user trace panel
pending a cross-repo PR. **ADR:** [0077](./adr/0077-phoenix-style-chat-dashboards.md).
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
live against the cluster (`/api/search/tags`, 2026-07-07):

| Attribute | Holds |
|---|---|
| `openinference.span.kind` | `LLM` or `EMBEDDING` — the chat/embedding split |
| `llm.input_messages.N.message.{role,content}` | each input message, per turn |
| `llm.output_messages.N.message.{role,content}` | each output message |
| `input.value` / `output.value` | full raw request/response JSON |
| `llm.model_name` | requested model |
| `llm.token_count.{prompt,completion,total}` | token usage for the span |

No new logging was added to get this — these dashboards are the first thing
to surface a capability that was already running.

## What's missing: identity

Spans carry **no `user.id`/`session.id`/`user.email`**, and the Envoy
access-log JSON (Loki's identity source, [ADR-0046](./adr/0046-per-user-attribution-otlp-envelope-repair.md))
carries no `trace_id` — so as shipped, there is no way to join a trace back to
a person. Envoy AI Gateway supports this via a generic header→span-attribute
mapping, `controller.spanRequestHeaderAttributes` (a Helm value on the `aieg`
controller app — comma-separated `<http-header>:<otel-attribute>` pairs).
Authorino already stamps `x-oidc-user-id`/`x-oidc-email` on every request
before ext-proc sees it, so the fix is one Helm value in the private
`ai-helm-values` repo:

```yaml
# environments/prod/values/aieg.yaml
controller:
  spanRequestHeaderAttributes: "x-oidc-user-id:user.id,x-oidc-email:user.email"
```

This is deliberately **not** bundled into the same change as the dashboards —
it's reviewed on its own in `ai-helm-values` because it's a genuine step up in
privacy exposure: full chat content already existed in Tempo, but this makes
it **directly attributable to a named person** by anyone who can use the
`chats-by-user` dashboard or query Tempo directly. See ADR-0077's
Consequences section.

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
  traffic — not `label_values(email)` like `per_user.py`/`jwt_tokens.py`. The
  aggregate panels (Loki-filtered on `email="$user"`) work today. The
  per-user trace panel queries
  `{ resource.service.name = "core-gateway" && span.openinference.span.kind = "LLM" && span.user.email = "$user" }`
  — it shows **"No data" until the `spanRequestHeaderAttributes` PR above
  merges** and new traffic flows; no dashboard change is needed once it does.

⚠️ **No raw user input is ever interpolated into SQL.** The `$user` variable's
*available options* come from a static-realm-id query; the *selected* value
only ever reaches a Loki/Mimir label matcher or a TraceQL attribute
comparison — never a second SQL string — so there's no SQL-injection surface
from a manipulated `?var-user=` URL param.

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
# empty until the ai-helm-values PR merges; populated after
```
