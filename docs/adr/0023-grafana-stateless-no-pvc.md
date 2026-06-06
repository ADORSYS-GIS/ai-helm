# ADR-0023: Grafana runs stateless (no persistent volume)

**Status:** Accepted
**Date:** 2026-06-06
**Deciders:** @stephane-segning

## Context

The platform aims to be **stateless** in the cluster: durable state lives in
external/managed backends (CNPG Postgres, redis-ha, Hetzner object storage,
`ssegning-aws` for secrets), and the workloads this repo deploys should be
reconstructible from Git + those backends with no per-pod disk to babysit.

Grafana was the exception — the `grafana/grafana` child of the observability
orchestrator (ADR-0020) set `persistence.enabled: true` (a 2 Gi PVC for
`/var/lib/grafana`, backing the embedded SQLite). But Grafana here needs no
durable disk: **dashboards are code** (grafana-operator + the
`grafana-foundation-sdk` JSON, regenerated and drift-checked in CI) and
**datasources are provisioned** from the same chart valuesObject. The only thing
the PVC held was throwaway runtime state (sessions, the unused SQLite) — a
stateful liability (node-pinned RWO volume, backup question, drift from Git)
buying nothing.

## Decision

**Run Grafana stateless: `persistence.enabled: false`** in the `grafana` child of
`charts/observability/values.yaml`, so the data dir is an `emptyDir` and **no
PVC is rendered**. A fresh pod rebuilds identical state at startup from the
provisioned datasources + the operator/sidecar-mounted dashboards. This makes
Grafana match the platform's stateless posture; nothing else in its config
(cert/SSO wiring in `environments/*/deps/grafana`, dashboard provisioning) changes.

## Consequences

**Positive**
- Grafana is now reconstructible from Git alone — no node-pinned PVC, no backup
  story, no disk drift. Reschedules freely.
- One less stateful component; reinforces "persistence lives in managed backends,
  not in pod volumes" as a platform principle.

**Negative**
- **Runtime state is discarded on every pod restart/reschedule** — sessions, and
  any change made *through the Grafana UI* rather than as code. This is by design:
  UI-authored dashboards are not the workflow here (dashboards-as-code is), so
  treat the UI as read-only/exploratory. Anything worth keeping must be committed
  as code.
- The first reconcile after this lands **deletes the existing PVC** and its
  contents (acceptable — it was throwaway state).

**Neutral / follow-ups**
- If a future need for true Grafana persistence appears (e.g. UI-authored
  artifacts that can't be code), the right answer is an **external database**
  (point Grafana at CNPG), not a PVC — keeping the pod stateless. Would warrant a
  superseding ADR.

## Alternatives considered

- **Keep the PVC** — rejected: it persisted only throwaway state while adding a
  node-pinned RWO volume and a backup/drift liability; dashboards + datasources
  are already code.
- **External DB (CNPG) for Grafana now** — rejected as premature: nothing today
  needs cross-restart Grafana state. Kept as the documented path if that changes.

## Related

- Commit: `59607f1` (the implementing change)
- Builds on: ADR-0020 (observability App-of-Apps — where the Grafana child lives)
- Charts/files touched: `charts/observability/values.yaml` (the `grafana` child's `persistence`)
