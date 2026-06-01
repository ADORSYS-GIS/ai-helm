# ADR-0019: Factor Coder into an App-of-Apps orchestrator (db + app as separate Applications)

**Status:** Accepted
**Date:** 2026-06-01
**Deciders:** @stephane-segning

## Context

Coder shipped as two independent flat entries in `charts/apps/values.yaml`:
`coder-db` (a CloudNativePG `Cluster` leaf chart) and `coder` (the upstream
Coder OCI chart + an ingress `Certificate` via the ADR-0018 `depsOverlay`).
They synced as two unrelated Applications with no grouping. The maintainer
asked to factor them under one **coder orchestrator** so the database and the
workload deploy as distinct-but-grouped Applications (their own sync/health/
rollback surface) under a single parent — the orchestrator-plus-leaves intent
of ai-models (ADR-0012) and librechart (ADR-0014).

Two constraints shaped the mechanism:
1. The Coder workload is an **upstream OCI chart** deployed as an ArgoCD
   *source* (not a local chart). Wrapping it as a Helm dependency needs a
   committed `Chart.lock`, which can't be generated where the OCI registry
   isn't reachable at build time, and forces an ugly `coder.coder.*` double
   nesting of values.
2. The two children are **fixed and heterogeneous** (one local Helm chart;
   one OCI chart + a kustomize cert overlay) — the opposite of the
   homogeneous, dynamically-sized fan-out (N models, 3 leaves) that an
   ApplicationSet List generator is good at.

## Decision

Add `charts/coder` as an **App-of-Apps orchestrator** that renders **two
`Application` CRs directly via plain Helm** (not an ApplicationSet):

- `coder-db` — single source, the local `charts/coder-db` leaf (sync-wave 1).
- `coder-app` — multi-source: Source A = the Coder OCI chart deployed as an
  ArgoCD source with its `valuesObject` inline (exactly as the old flat app,
  `helm.releaseName: coder` preserved so resource names don't churn); Source B
  = the `environments/<env>/deps/coder` kustomize overlay for the ingress
  `Certificate` (issuer patched per env, ADR-0018). Sync-wave 2.

The orchestrator entry in `charts/apps/values.yaml` (`name: coder`,
`controlPlane: true`, `path: charts/coder`) replaces the two flat entries. As
a control object it targets in-cluster/argocd; both rendered children target
`home-remote` via the `coder.argocd.destinationClusterRef` guard (ADR-0017).

## Consequences

**Positive**
- Database and workload are now grouped under one parent (`aii-coder`) with
  their own per-child Application surface — pause/rollback/inspect each
  independently.
- The Coder workload keeps deploying as an OCI *source* (the proven path) —
  no OCI-as-Helm-dependency `Chart.lock` burden, no `coder.coder.*` double
  nesting.
- `helm template charts/coder` shows the final child Application CRs directly
  (no ApplicationSet controller-time goTemplate indirection to debug).
- The cert stays a per-env overlay knob, consistent with grafana/lightbridge.

**Negative**
- Diverges from the ApplicationSet orchestrator convention (ai-models /
  librechart). Justified by the fixed-heterogeneous-children case; documented
  here and in the chart so the divergence is intentional, not drift.
- Two-layer rendering: `helm template charts/apps` shows `aii-coder`, not the
  children; verifying the children needs `helm template charts/coder`.

**Neutral / follow-ups**
- Cutover: `aii-coder-db` (old flat) is pruned; the workload moves from the
  old `aii-coder` flat Application to the new `coder-app` child. ArgoCD
  re-adopts the live resources via tracking labels — coordinate the sync.
- A second environment overrides the child cert issuer / values via the
  orchestrator's `app.values` + the env overlay; no new machinery needed.

## Alternatives considered

- **ApplicationSet + local wrapper chart** (wrap Coder OCI as a Helm dep in a
  `charts/coder-app` leaf, path-based child like librechart) — rejected:
  needs a committed `Chart.lock` for the OCI dep (unbuildable where the
  registry isn't reachable at `helm dependency build` time) and forces
  `coder.coder.*` double-nested values.
- **ApplicationSet + inline OCI source in the element** — rejected: mixing a
  path-based local child and an OCI multi-source child means controller-time
  `goTemplate` `if/else` plus `valuesYaml` string nindent — exactly the
  escaping pain ADR-0012 flags, for only two static children.
- **Keep two flat apps** — rejected: no grouping, which was the ask.

## Related

- Builds on: ADR-0012, ADR-0014 (orchestrator-plus-leaves intent),
  ADR-0017 (destination guard), ADR-0018 (cert via per-env overlay)
- Charts/files: `charts/coder/` (new orchestrator), `charts/coder-db/`
  (unchanged leaf), `charts/apps/values.yaml` (flat entries → orchestrator),
  `environments/{base,prod}/deps/coder/` (cert overlay, retained)
