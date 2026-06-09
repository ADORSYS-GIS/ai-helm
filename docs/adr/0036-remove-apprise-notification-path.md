# ADR-0036: Remove the Grafana apprise path; keep a lean apprise-api for the agent

**Status:** Accepted
**Date:** 2026-06-09
**Deciders:** @stephane-segning

## Context

Two distinct things used Apprise, and they were entangled:

1. **Grafana alerting** routed through an external Alertmanager override pointing
   at `grafana-apprise-adapter` (observability ns) → `apprise-api` (monitoring ns)
   → channels. This is redundant: Grafana's embedded Alertmanager + native contact
   points (and Prometheus/Mimir Alertmanager) notify directly.
2. **opencode-k8s-agent** (the 12-hourly AI cluster-health CronJob) has **no
   built-in notifier** — its `run.sh` does `curl -X POST "$APPRISE_API_URL/notify"
   -F "urls=$APPRISE_URLS" …`, i.e. it depends on `apprise-api`'s **stateless
   `/notify`** endpoint, passing the channel URLs in the request body.

The live `apprise-api` was `0/1` — not because the service is wrong, but because
its Deployment mounted the `apprise-channels` secret (an unfilled placeholder) at
`/apprise-config`, so the pod hung `ContainerCreating`. That stored-config mount
only ever served the Grafana adapter path; the agent never needed it.

An earlier revision of this ADR removed `apprise-api` entirely on the mistaken
assumption that the agent could notify without it. It cannot — so the scope is
corrected here.

## Decision

- **Remove the Grafana apprise path:** delete `grafana-apprise-adapter`
  (observability `extraObjects`) and revert Grafana `unified_alerting` from the
  external Alertmanager (the adapter) back to its **embedded** Alertmanager.
  Grafana/Alertmanager notify natively.
- **Keep `apprise-api`, but lean and stateless:** it stays solely as
  `opencode-k8s-agent`'s notify gateway. Drop the `apprise-channels` secret /
  persistence mount and the app-scoped deps overlay (the agent supplies channel
  URLs per request, so no stored config is needed) and run it
  `APPRISE_STATEFUL_MODE: disabled`. This also fixes the `0/1` hang.
- **Retire the `apprise-channels` secret** (`environments/{base,prod}/deps/apprise-api`
  deleted) — it was only for the removed adapter path.

`opencode-k8s-agent` keeps its `APPRISE_API_URL` → `apprise-api`.

## Consequences

**Positive**

- Removes the redundant Grafana→adapter→api indirection and the custom adapter
  image; Grafana uses first-class contact points.
- `apprise-api` actually runs now (the broken stored-config mount is gone), so the
  agent can deliver once its own `opencode-k8s-agent-secret` (with `APPRISE_URLS`)
  is provisioned.

**Negative**

- The platform still runs a small `apprise-api` Deployment (one purpose: the
  agent's report delivery). Acceptable — the agent has no other notifier.
- Grafana native contact points are not configured yet; until they are, Grafana
  has no outbound alert delivery. Not a regression (the apprise alert path was
  already non-functional).

**Neutral / follow-ups**

- Provision `opencode-k8s-agent-secret` (`OPENCODE_API_KEY`, `APPRISE_URLS`,
  `KEYCLOAK_CLIENT_SECRET`) — until then the agent exits 1 (`APPRISE_URLS empty`).
- Configure native Grafana contact points (commented `contactpoints.yaml` /
  `policies.yaml` scaffolding shows the shape — point them at real channels, not
  the removed adapter).
- Verify on deploy that `APPRISE_STATEFUL_MODE: disabled` serves `/notify` as the
  agent expects.

## Alternatives considered

- **Remove apprise-api entirely** (the earlier, withdrawn decision) — rejected:
  the agent's `run.sh` hardwires a POST to `apprise-api/notify` and has no
  embedded notifier, so removing the service leaves the agent unable to notify.
- **Keep the full Grafana→adapter→api path** — rejected: redundant with native
  Grafana/Alertmanager notifications and carries an extra image + hop.
- **Also remove opencode-k8s-agent** — not chosen; the AI cluster-health report is
  wanted, it just needs its secret filled.

## Related

- Charts/files touched: `charts/apps/values.yaml` (lean apprise-api + agent),
  `charts/observability/values.yaml` (adapter + alertmanager override removed),
  `environments/{base,prod}/deps/apprise-api` (deleted),
  `environments/prod/deps/grafana/ciliumnetworkpolicy.yaml`, `docs/releasing.md`.
- Relates to: [ADR-0020](./0020-observability-app-of-apps-orchestrator.md),
  [ADR-0024](./0024-right-size-observability-tiny.md).
</content>
