# ADR-0046: Repair per-user attribution — flatten the OTLP access-log envelope at Alloy

**Status:** Accepted
**Date:** 2026-06-12
**Deciders:** @stephane-segning

## Context

The flagship per-user usage dashboard (`envoy-ai-gateway-per-user`,
ticket [#357](https://github.com/ADORSYS-GIS/ai-helm/issues/357)) has been
empty since rollout. The live audit
([docs/observability-dashboard-research.md](../observability-dashboard-research.md))
isolated the break to a single seam: Envoy's OpenTelemetry access-log sink
delivers the `format.json` fields as OTLP log **attributes**, and Alloy's
`otelcol.exporter.loki` serializes the stored line as
`{"attributes":{...},"resources":{...}}`. The ADR-0005
`ai_gateway_user_attribution` stage expects top-level `user_id`/`azp` keys,
so it never promoted labels; the stream landed as
`service_name="unknown_service"` (no `service.name` resource was set); and
every dashboard selector `{user_id=~...,azp=~...}` and `| json` field
reference missed. The data itself is intact and accurate — re-querying the
nested form live returned 21 distinct users with real token totals over
24 h. ADR-0005's decision (Authorino headers → access log → Loki labels)
stands; its assumed *line shape* was wrong.

## Decision

1. **Name the stream deterministically.** Alloy pins
   `service_name="envoy-ai-gateway"` on matched gateway access-log streams
   via `stage.static_labels` — deliberately *not* relying on the
   `otelcol.exporter.loki` resource-translation rules or Loki's
   `discover_service_name` fallback (which produced `unknown_service`).
   The Envoy sink additionally sets resource
   `service.name: envoy-ai-gateway`
   (`charts/core-gateway/templates/envoy-proxy.yaml`) to document intent
   at the source.
2. **Flatten at Alloy, scoped to gateway logs only.** The
   `ai_gateway_user_attribution` stage becomes a `stage.match` anchored on
   the `otel_envoy_accesslog` marker (`resources.log_name`, present in
   every gateway line and verifiable against data already stored) that
   (a) extracts the `attributes` object and **rewrites the stored line to
   it** (`stage.output`), so the line is flat JSON and LogQL `| json`
   yields `user_id`, `azp`, `gen_ai_request_model`,
   `gen_ai_usage_total_tokens`, `duration`, … as designed; (b) promotes
   `user_id`, `azp`, and `model` (← `gen_ai.request.model`, bounded by our
   model catalog, ~10–20 values) to labels; (c) maps Envoy's `-`
   placeholder to empty **by exact match** (never substring — UUIDs
   contain `-`) so absent identities produce no label. Non-gateway OTLP
   logs pass through untouched.
3. **Dashboards query the flat contract.** The generated per-user board
   (`tools/dashboards/.../per_user.py`) anchors every selector on
   `service_name="envoy-ai-gateway"`, uses the `model` label for its
   variable (the old `label_values(gen_ai_request_model)` queried a
   non-existent label), and guards every `unwrap` with `__error__=""`
   (numeric fields arrive as strings; absent ones as `-`).

This ADR **supplements ADR-0005** (mechanism repair; the decision and
cardinality budget there are unchanged) — same relationship ADR-0011 has
to it for the header payload.

## Consequences

**Positive**
- The per-user board works against data already flowing — no new
  components, no Envoy/Authorino changes beyond one resource attribute.
- The flat line is the *documented* contract
  (docs/per-user-observability.md examples become correct as written) and
  is cheaper to store/query than the double-nested envelope.
- A named stream (`service_name="envoy-ai-gateway"`) gives every future
  gateway-log query a precise, cheap anchor.

**Negative**
- The stored line loses the OTLP `resources` sub-object (cluster/zone/node
  names — `cluster` survives as a Loki external label; pod identity is in
  the line via `k8s.pod.name`). Acceptable: nothing queried `resources`.
- Pre-fix log lines keep the old nested shape and `unknown_service` name;
  the dashboard shows attributed data only from rollout forward (history
  was never attributed anyway — the labels didn't exist).
- One more label (`model`) on gateway streams; bounded cardinality,
  budgeted in ADR-0005's terms.

**Neutral / follow-ups**
- Rolls out with the next release tag (tag-pinned deploys, ADR-0031);
  validate the labels exist in Loki post-rollout per
  docs/per-user-observability.md "Verifying it works".
- If AIEG ever exports `gen_ai_*` Prometheus metrics here, a Mimir-based
  usage view can complement (not replace) the Loki attribution path.

## Alternatives considered

- **Fix only the dashboard queries against the nested body**
  (`attributes_user_id` etc.), no Alloy change — rejected: leaves the
  ADR-0005 label promotion permanently broken (no `label_values`
  variables, every query a full-body JSON parse over all OTLP streams),
  and freezes the accidental double-nested envelope as the contract.
- **Parse nested keys in Alloy but keep the stored line as-is** — rejected:
  labels would work but every body-field query (`| json`) still needs the
  `attributes_`-prefixed names, contradicting the documented contract and
  keeping the storage overhead.
- **Have Envoy put the JSON in the OTLP body instead of attributes** — not
  available: Envoy Gateway's `accessLog.format.json` + OTel sink shape is
  fixed upstream (the body carries only the text format).
- **Move usage attribution to Prometheus metrics (extproc OTel metrics →
  Mimir)** — rejected for now: no such metrics are exported today
  (verified — zero `gen_ai_*`/`ai_gateway_*` series in Mimir), and
  per-user metric labels would re-open the cardinality question ADR-0005
  already settled in Loki's favor.

## Related

- [ADR-0005](./0005-per-user-attribution-via-authorino-headers.md) — supplemented by this ADR
- [ADR-0011](./0011-oidc-downstream-headers.md) — the `x-oidc-*` header payload
- [ADR-0045](./0045-scrape-first-dashboard-sourcing.md) — the sourcing policy decided alongside
- [ADR-0008](./0008-python-dashboard-generation.md) — the pipeline that generates the consuming dashboard
- [docs/per-user-observability.md](../per-user-observability.md) — the repaired pipeline walkthrough
- [docs/observability-dashboard-research.md](../observability-dashboard-research.md) — the evidence base
- Tickets: [#341](https://github.com/ADORSYS-GIS/ai-helm/issues/341), [#357](https://github.com/ADORSYS-GIS/ai-helm/issues/357)
