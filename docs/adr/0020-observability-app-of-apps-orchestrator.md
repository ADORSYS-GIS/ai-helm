# ADR-0020: Factor the observability stack into an App-of-Apps orchestrator (+ a secrets app)

**Status:** Accepted
**Date:** 2026-06-01
**Deciders:** @stephane-segning

## Context

The observability stack was ten independent flat entries in
`charts/apps/values.yaml` (prometheus-operator-crds, alloy, kube-state-metrics,
node-exporter, grafana-operator, mimir, loki, tempo, grafana,
observability-dashboards) with no grouping, and their secrets (S3 creds,
grafana admin/keycloak) were provisioned entirely externally
(ai-ops-secrets.git). The maintainer asked to factor them under one
**observability orchestrator** (db/collectors/visualization as distinct
Applications under one parent, mirroring the coder split ADR-0019) plus a
**dedicated secrets app**, "as elegant as possible". Two facts shaped it:
the stack is partly stateful (mimir/loki/tempo) and currently the healthiest
part of the cluster; and the namespace needs `privileged` Pod Security so
Alloy/node-exporter's hostPath workloads pass admission under k3s's baseline
default (the `global.namespacePodSecurity` mechanism added just prior).

## Decision

Add `charts/observability` as an **App-of-Apps orchestrator** (same shape as
coder, ADR-0019) that renders one workload `Application` per child from a
`children` list, all targeting `home-remote`/`observability`:

- The ten components move in verbatim (sources + valuesObjects unchanged;
  YAML anchors relocated alongside them). Sync-waves preserved (-3…1).
- **`podSecurityEnforce: privileged`** on the orchestrator → every child gets
  `managedNamespaceMetadata` PSS labels (the per-cluster knob now lives on the
  orchestrator instead of `charts/apps`'s map). Grafana keeps its ingress
  `Certificate` via the `depsOverlay` (the orchestrator template supports it).
- A new **`observability-secrets`** child renders ExternalSecrets for
  `mimir-s3`/`loki-s3`/`tempo-s3`/`grafana-admin`/`grafana-keycloak` from a
  kustomize overlay (`environments/<env>/deps/observability-secrets`,
  store patched per env). It ships **`enabled: false`** with placeholder
  remoteRefs — activating it before the real `ssegning-aws` keys are filled
  (and the external provisioner stops managing the same Secret names) would,
  with `creationPolicy: Owner`, clobber the live creds and break the stack.

The orchestrator entry in `charts/apps` (`name: observability`,
`controlPlane: true`, `path: charts/observability`) replaces the ten flat
entries; `charts/apps`'s `namespacePodSecurity` map is emptied (the stack that
needed it now self-manages PSS).

## Consequences

**Positive**
- One parent (`aii-observability`) groups the whole stack; each component
  keeps its own Application surface (pause/rollback/inspect).
- A single place owns observability secrets (when activated), retiring the
  ai-ops-secrets dependency for this stack.
- PSS elevation is centralised on the orchestrator and stays a per-cluster
  knob (`podSecurityEnforce`).
- `charts/apps/values.yaml` shrinks by ~1600 lines.

**Negative**
- Diverges from the ApplicationSet orchestrator convention (like coder) —
  justified by heterogeneous children with large inline valuesObjects, which
  an ApplicationSet List generator handles poorly. Documented.
- Cutover churn: the ten Applications rename (`aii-mimir` → `mimir`, …); ArgoCD
  prunes the old + recreates under the orchestrator — a brief telemetry gap and
  local PVC churn on mimir/loki/tempo. **S3-backed block data is safe.**

**Neutral / follow-ups**
- The secrets app is inert until its remoteRefs are filled and `enabled: true`.
- A second environment overrides `podSecurityEnforce` / child values via the
  orchestrator + env overlays; no new machinery.

## Alternatives considered

- **ApplicationSet orchestrator** (like ai-models/librechart) — rejected: the
  ten children are fixed + heterogeneous with large inline valuesObjects;
  inlining them via controller-time goTemplate is the escaping pain ADR-0012
  flags. App-of-Apps renders the final Application CRs directly (debuggable
  with `helm template`), consistent with coder.
- **Keep ten flat apps** — rejected: no grouping, no secrets app (the ask).
- **Enable the secrets app immediately** — rejected: placeholder remoteRefs +
  `creationPolicy: Owner` over live externally-provisioned Secrets would break
  the stack. Ship disabled.

## Related

- Builds on: ADR-0019 (App-of-Apps pattern), ADR-0017 (destination guard),
  ADR-0018 (depsOverlay + per-env overlays + PSS knob)
- Charts/files: `charts/observability/` (new), `charts/apps/values.yaml`
  (ten entries → orchestrator; `global` slimmed),
  `environments/{base,prod}/deps/observability-secrets/` (new)
