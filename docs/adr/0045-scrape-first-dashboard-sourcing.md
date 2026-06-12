# ADR-0045: Scrape-first dashboard sourcing

**Status:** Accepted
**Date:** 2026-06-12
**Deciders:** @stephane-segning

## Context

Epic [#341](https://github.com/ADORSYS-GIS/ai-helm/issues/341) asked which
services need observability dashboards (tickets #354/#355). The live audit
([docs/observability-dashboard-research.md](../observability-dashboard-research.md))
found that every dead dashboard we ship — six of the thirteen imported
gnetId boards, plus our own per-user board — is dead because its *data
source is missing*, not because the dashboard is wrong: only 9 monitor CRs
exist cluster-wide, and Mimir/Loki don't even scrape themselves. This repo
has also shipped three phantom/incompatible gnetIds in the past (21048 →
404, 18030 → a k6 board, 17931 → InfluxDB — see the comments in
`charts/observability/values.yaml`). The pattern to break is *selecting
dashboards as if data were a given*.

## Decision

1. **Scrape-first.** Never import a dashboard before its metrics verifiably
   exist in Mimir; conversely, prefer enabling a scrape that revives an
   already-imported board over any new dashboard work (Mimir + Loki
   self-monitoring ServiceMonitors are the immediate cases).
2. **Adopt verified community boards for commodity services.** gnetId +
   revision must be verified against the grafana.com API *and* the board's
   query expressions checked against metrics our deployment emits before
   import. Current adoptions from the research: Keycloak **23338**
   (micrometer-native, mirrors the official keycloak-grafana-dashboard
   repo) once Keycloak metrics are scraped; Percona's repo JSON for
   MongoDB once an exporter exists (the grafana.com MongoDB boards are all
   stale).
3. **Custom dashboards-as-code (ADR-0008 foundation-sdk) only for bespoke
   domain boards** — per-user usage, envoy-ratelimit budget enforcement,
   Authorino — where no community equivalent exists (verified: grafana.com
   has zero results for both ratelimit and Authorino).
4. **No dashboards for unreachable data.** Model serving runs on the home
   GPU cluster (ADR-0022) with no path into this Mimir; its observability
   is blocked on a remote-write/federation decision (future ADR), not on
   dashboard selection.

## Consequences

**Positive**
- Two dead boards (Mimir, Loki) come alive with zero dashboard work, and
  the import-into-a-void pattern stops.
- gnetId verification becomes a stated gate, not tribal knowledge — the
  research doc §6 records the exact commands.
- Custom-board effort is reserved for the places it's genuinely needed.

**Negative**
- Slower "time to dashboard" for a new service: the scrape (exporter,
  monitor CR, NetworkPolicy allow) must land first.
- Some scrape gaps are cross-repo (redis-exporter → home-os; cert-manager/
  ESO/Traefik ServiceMonitors → external installs; Cilium → hetzner-k8s)
  and can only be *recorded* here, not fixed here.

**Neutral / follow-ups**
- P1 sequencing (Keycloak, ratelimit, Authorino, MongoDB) per the research
  doc §5; each lands as its own ticket.
- The per-user board's specific repair is a separate technical decision —
  [ADR-0046](./0046-per-user-attribution-otlp-envelope-repair.md).

## Alternatives considered

- **Research/import dashboards per gap service directly** (the literal
  reading of #355) — rejected: §2 of the research shows
  imported-but-dead boards are the dominant failure mode; more imports
  without scrapes just grows the dead pile.
- **Build everything custom via the ADR-0008 pipeline** — rejected:
  commodity services (Keycloak, MongoDB, k8s) have well-maintained
  community boards; rebuilding them is waste and a maintenance burden.
- **Trust grafana.com search results / IDs from memory** — rejected by
  scar tissue: three prior phantom or incompatible imports.

## Related

- [docs/observability-dashboard-research.md](../observability-dashboard-research.md) — the evidence base (tickets #354/#355)
- [ADR-0046](./0046-per-user-attribution-otlp-envelope-repair.md) — the per-user pipeline repair (decided alongside, recorded separately)
- [ADR-0008](./0008-python-dashboard-generation.md) — dashboards-as-code pipeline
- [ADR-0022](./0022-self-hosted-gpu-model-federated-into-gateway.md) — why model serving is on the other cluster
- Tickets: [#341](https://github.com/ADORSYS-GIS/ai-helm/issues/341), [#355](https://github.com/ADORSYS-GIS/ai-helm/issues/355)
