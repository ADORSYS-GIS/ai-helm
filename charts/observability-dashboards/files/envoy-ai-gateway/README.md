# AI Gateway — per-user activity dashboard

**File:** `per-user.json`
**Loki datasource UID:** `loki`
**Folder:** `AI Gateway` (provisioned by `charts/observability-dashboards/templates/folders.yaml`)
**Operator CR name:** `envoy-ai-gateway-per-user`

## What it shows

End-to-end per-user view of traffic through the Envoy AI Gateway, sliced by
Keycloak user (`user_id` = JWT `sub`), authorized party (`azp` = client_id),
and model.

| Panel | Question it answers |
|---|---|
| Requests / Unique users / Total tokens / p95 latency (stats row) | "What's happening right now, in one glance" |
| Requests per user / minute (stacked timeseries) | "Who's driving the volume, and when" |
| Top users by requests (table) | "Who are the heaviest callers right now" |
| Model distribution (pie) | "What models is the selected scope using" |
| Latency per user — p50 / p95 (timeseries) | "Is anyone seeing slow responses" |
| Failed requests per user (stacked bar) | "Where are the 5xx errors landing" |
| Token usage per user (timeseries) | "Who's burning tokens" |

## Variables

All three are label-backed (ADR-0046), multi-select with All:

- **`azp`** — Keycloak client_id (`label_values({service_name="envoy-ai-gateway"}, azp)`). Use to split human vs SA traffic (see `docs/authorino-service-account-bypass.md` for the SA allowlist).
- **`user_id`** — Keycloak user `sub` (`label_values({service_name="envoy-ai-gateway", azp=~"$azp"}, user_id)`). Cascades from `azp`.
- **`model`** — `gen_ai.request.model`, promoted to the `model` label by Alloy. Filters all panels.

## Data path

The dashboard relies on labels added by the per-user attribution pipeline
(ADR-0005, repaired by ADR-0046):

```
JWT → Authorino response headers (x-oidc-user-id, x-oidc-azp; full x-oidc-* contract in ADR-0011)
    → Envoy access-log OTel sink (fields arrive as OTLP ATTRIBUTES)
    → OTLP → Alloy (direct; the -usage collector was removed)
    → loki.process "ai_gateway_user_attribution"
        (flattens {"attributes":{...}} → line; promotes labels;
         pins service_name=envoy-ai-gateway)
    → Loki labels {service_name, user_id, azp, model}
```

The dashboard shows **attributed traffic only** — unauthenticated requests
carry no identity labels by design. If the dashboard is empty, walk the flow
backwards using the
[troubleshooting matrix in `docs/per-user-observability.md`](../../../../docs/per-user-observability.md#troubleshooting).

## Editing

**Do not hand-edit `per-user.json`.** It is GENERATED (ADR-0008) from
`tools/dashboards/src/dashboards/envoy_ai_gateway/per_user.py`:

```bash
cd tools/dashboards
# edit src/dashboards/envoy_ai_gateway/per_user.py
uv run dashboards build       # regenerates per-user.json — commit both
uv run dashboards check       # what CI runs; fails on drift
```

Keep `uid: envoy-ai-gateway-per-user` stable — changing it breaks bookmarks
(and the epic's source-of-truth link). To prototype in Grafana, edit a *copy*
in the UI, then port the change back into the generator module.
