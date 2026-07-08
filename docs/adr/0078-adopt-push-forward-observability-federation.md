# ADR-0078: Adopt Push-Forward Mode for multi-upstream observability federation

**Status:** Proposed
**Date:** 2026-07-08
**Deciders:** @stephane-segning
**Relates to:** [docs/multi-upstream-observability.md](../multi-upstream-observability.md)

## Context

The central observability cluster (LGTM — Loki, Grafana, Tempo, Mimir) currently
ingests telemetry only from its own cluster. Components running outside this
cluster, such as a home GPU cluster for model-serving and future tenant clusters,
have no path to push metrics, logs, or traces into the central stores. This gap
was identified in docs/observability-gaps.md and blocked on a federation decision.

Three broad federation strategies exist, and we need a documented, repeatable
approach for onboarding new upstream clusters without over-engineering for a
scale we do not yet have.

## Decision

Adopt **Push-Forward Mode (Headless Upstreams)** for multi-upstream observability
federation. Upstream clusters run Alloy collectors that immediately stream
telemetry over HTTPS/gRPC to the central cluster's ingress endpoints. Upstreams
do not store observability data locally — the collector's WAL or disk-backed
queue provides only transient buffering for short central outages.

Concretely:

- **Metrics:** upstream Alloy uses prometheus.remote_write to push to central
  Mimir's /api/v1/push endpoint, with external_labels (cluster, tenant_id)
  stamped at the edge for isolation.
- **Logs:** upstream Alloy uses loki.write to push to central Loki's Push API
  endpoint, with cluster/tenant_id added via loki.process.
- **Traces:** upstream Alloy uses otlp.exporter to push OTLP spans over gRPC
  to central Tempo's :4317 endpoint.

The central cluster must expose its stores via Ingress (currently ClusterIP-only)
and add CiliumNetworkPolicy rules to allow external push traffic.

## Consequences

### Positive

- **Simple architecture:** single direction of data flow, fewer failure modes,
  easy to debug (curl/grpcurl against ingress)
- **Stateless upstreams:** no local storage to maintain on tenant clusters
- **Reuses existing components:** Alloy is already deployed and understood in
  the central cluster
- **Low operational overhead:** onboarding a new upstream is a 5-step SOP
  (provision creds, deploy Alloy, expose Ingress, verify, add dashboards)

### Negative

- **Data loss on extended central outage:** metrics/logs survive hours (disk
  WAL/queue), traces are in-memory only and drop on restart
- **Central cluster is a single point of failure** for all observability
- **No native multi-tenancy:** isolation is label-based (cluster + tenant_id
  labels), not via X-Scope-OrgID. Data mixing risk if upstream misconfigured

### Neutral / follow-ups

- Ingress rules and CiliumNetworkPolicy must be added to the central cluster
  (no changes to Mimir/Loki/Tempo config)
- Basic auth for the first upstream (PoC), migrate to mTLS before onboarding
  a second production upstream
- Native multi-tenancy (X-Scope-OrgID) is a config-only upgrade path if
  regulatory isolation or per-tenant rate limiting is needed later

## Alternatives considered

- **Pull / Federation (rejected):** Central cluster scrapes or federates from
  upstream Prometheus servers. No data loss on central outage but adds
  operational complexity (reachable endpoints, TLS, auth on every upstream)
  and scrape-interval delay. May become relevant for cross-cluster PromQL
  queries at a later stage.

- **Local Store + Replicate (rejected):** Each upstream runs a full
  observability stack with long retention and periodically ships a copy.
  Zero data loss but disproportionately expensive to maintain storage on
  every upstream at our current scale.

## Related

- Docs: [docs/multi-upstream-observability.md](../multi-upstream-observability.md) (the *how*)
- Docs: [docs/observability-gaps.md](../observability-gaps.md) (gap inventory that prompted this decision)
- Docs: [docs/architecture/08-observability.md](../architecture/08-observability.md) (current pipeline)
- ADR: [ADR-0062: Self-Signed CA with cert-manager](./0062-grafana-llm-assistant-via-internal-gateway.md) (mTLS foundation)
- Charts touched: charts/observability/ (Ingress rules for stores)
