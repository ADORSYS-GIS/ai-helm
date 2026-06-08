# ADR-0036: Remove the apprise notification path (apprise-api + grafana-apprise-adapter)

**Status:** Accepted
**Date:** 2026-06-09
**Deciders:** @stephane-segning

## Context

Platform alert notifications were routed through a three-hop apprise chain:

```
Grafana (unified alerting, external alertmanager)
  → grafana-apprise-adapter  (observability ns; translates Grafana webhooks → Apprise)
    → apprise-api             (monitoring ns; fans out to Discord/Slack/email/…)
```

This predates the current observability stack. It was also never fully wired —
`apprise-api` was perpetually `Degraded` because its `apprise-channels` secret
(`environments/*/deps/apprise-api`) was an unfilled placeholder in the
`ssegning-aws` store. Meanwhile Grafana's own unified alerting (embedded
Alertmanager + native contact points) and Prometheus/Mimir Alertmanager can send
notifications directly, making the apprise indirection redundant.

## Decision

Remove the entire apprise notification path:

- Delete the **`apprise-api`** Application (`charts/apps/values.yaml`) and its
  deps overlays (`environments/{base,prod}/deps/apprise-api`, the
  `apprise-channels` ExternalSecret placeholder).
- Delete the **`grafana-apprise-adapter`** Deployment/Service (the grafana
  child's `extraObjects` in `charts/observability/values.yaml`).
- Revert Grafana's `unified_alerting` from the **external** Alertmanager override
  (which pointed at the adapter) back to its **embedded** Alertmanager, so native
  contact points handle notifications.

Notifications are henceforth Grafana/Alertmanager-native.

`opencode-k8s-agent` (the AI cluster-health CronJob) had an `APPRISE_API_URL`
override pointing at the `apprise-api` service. That override is **removed** so the
agent falls back to sending reports **directly** via `APPRISE_URLS` (from its own
`opencode-k8s-agent-secret`, the embedded apprise library) — it no longer depends
on the deleted service. Its report-delivery capability is preserved.

## Consequences

**Positive**

- Removes two unused/broken components and a perpetually-`Degraded` Application
  from the platform; resolves the dangling `apprise-channels` secret placeholder.
- Notifications use first-class Grafana/Alertmanager contact points (no custom
  adapter image, no extra hop, no separate `monitoring` namespace workload).

**Negative**

- Until native Grafana contact points / Alertmanager receivers are configured,
  there is no outbound alert delivery. Acceptable: the apprise path was already
  non-functional (Degraded, no channels secret), so this is not a regression in
  working behaviour.

**Neutral / follow-ups**

- Configure native Grafana contact points (the commented `contactpoints.yaml` /
  `policies.yaml` scaffolding in `charts/observability/values.yaml` shows the
  shape — point them at real channels instead of the removed adapter).
- The `monitoring` namespace may be left empty once `apprise-api` is pruned.

## Alternatives considered

- **Keep apprise-api, just fill the `apprise-channels` secret** — rejected: it
  adds a redundant hop and a custom adapter image to maintain when Grafana can
  notify channels natively.
- **Remove apprise-api but keep grafana-apprise-adapter** — rejected: the adapter
  exists only to forward to apprise-api; without it the adapter is dead weight and
  Grafana's external-alertmanager override would point at nothing.

## Related

- Charts/files touched: `charts/apps/values.yaml`,
  `charts/observability/values.yaml`,
  `environments/{base,prod}/deps/apprise-api` (deleted),
  `environments/prod/deps/grafana/ciliumnetworkpolicy.yaml`, `docs/releasing.md`.
- Relates to: [ADR-0024](./0024-right-size-observability-tiny.md),
  [ADR-0020](./0020-observability-app-of-apps-orchestrator.md) (observability stack).
</content>
