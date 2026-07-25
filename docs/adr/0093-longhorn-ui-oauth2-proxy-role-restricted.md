# ADR-0093: Gate the Longhorn UI with a dedicated, role-restricted oauth2-proxy

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** @stephane-segning

## Context

ADR-0092 deployed Longhorn (distributed block storage) scoped to the two
hand-joined Hetzner Robot GPU nodes, providing PVC storage where `hcloud-csi`
cannot reach. Longhorn ships a web UI with **no authentication of its own**
(`longhorn-frontend` Service, ClusterIP-only today) that grants full
volume/node management — including deleting volumes and detaching/evicting
replicas. This is a materially higher-stakes surface than the read-only
dashboard `homepage-auth` (ADR-0089) was built to gate: exposing it without a
deliberate access decision risks any authenticated platform user (or, if
mis-scoped, anyone at all) being able to destroy GPU-node model-cache storage.

## Decision

Expose the Longhorn UI publicly at `longhorn.ai.camer.digital` (Traefik
Ingress + `cert-home-cert-http` ACME HTTP-01, matching the platform's
standard pattern), fronted by a **dedicated** oauth2-proxy instance in
reverse-proxy mode — same shape as `homepage-auth`, but with one deliberate
addition: **access is restricted to a specific Keycloak client role, not any
authenticated user.**

Mechanism: a new Keycloak client `longhorn-proxy` carries a client role
`admin`, mapped by a dedicated client scope (`longhorn-proxy`, assigned as a
**default** client scope — always present, no explicit `--scope` needed) into
a multivalued `longhorn_roles` claim (mirrors the `mlflow_roles`/
`argo_workflows_roles` shape in `charts/keycloak-baseline`; **multivalued is
load-bearing** — ADR-0085 found a non-multivalued claim silently rejects
every login, even for a correctly-role-assigned user). oauth2-proxy is
configured with `--oidc-groups-claim=longhorn_roles --allowed-group=admin`,
so only users the operator explicitly grants the `admin` client role to can
reach the UI at all — everyone else's login succeeds against Keycloak but is
rejected by oauth2-proxy before ever reaching Longhorn.

Structurally: a new 2-child App-of-Apps orchestrator `charts/longhorn-auth`
(`longhorn-secrets` + `longhorn-auth`, sync-waves 0/1) — deliberately **not**
a 3-child orchestrator like `homepage`, because the Longhorn workload itself
is the separate, already-live, already-verified flat `aii-longhorn`
Application (ADR-0092); restructuring it into an orchestrator child would
mean ArgoCD deletes and recreates the entire running Longhorn stack under new
Application names, for zero functional benefit. Both new children colocate in
the existing `longhorn-system` namespace (auth colocated with what it
protects, matching `homepage-auth`'s own-namespace convention) — which
carries no NetworkPolicy/CiliumNetworkPolicy today (verified live), so no new
egress-allow rules are needed for oauth2-proxy to function; retrofitting a
default-deny baseline onto `longhorn-system` is explicitly out of scope here.

## Consequences

**Positive**
- The Longhorn UI's destructive capability is gated to an explicit,
  operator-managed allowlist (a Keycloak client role), not "every SSO user."
- Reuses the proven `homepage-auth`/`lakefs-auth` reverse-proxy-mode shape and
  the proven multivalued-claim lesson from ADR-0085 — no new failure modes
  introduced.
- Zero risk to the already-live `aii-longhorn` Application — it is untouched.

**Negative**
- One more Keycloak client + client scope + role to maintain manually
  (`charts/keycloak-baseline` is documentation only, per its own existing
  caveat — the realm is not reconciled by anything; a human must create/edit
  the live client to match).
- One more manual out-of-band secret (`longhorn_proxy_client_id/_secret/_cookie_secret`
  in `ssegning-aws`) before the Secret can sync.

**Neutral / follow-ups**
- `longhorn-system` has no egress NetworkPolicy baseline today (verified
  live) — this ADR does not change that. Hardening it is a separate decision
  if ever wanted, and must not accidentally break Longhorn's own already-working
  egress (chart/image pulls, CSI, etc.).
- If a second Longhorn-capable role tier is ever needed (e.g. read-only
  viewer), add a second client role + extend `--allowed-group` — the claim
  mechanism already supports multiple values.

## Alternatives considered

- **Any authenticated user (the `homepage-auth` shape, unmodified)** —
  rejected: the Longhorn UI's blast radius (destructive volume/node
  operations) doesn't match Homepage's read-only dashboard; a role gate costs
  one extra Keycloak client role and is worth it here.
- **Cluster-internal only (no public Ingress, kubectl port-forward /
  VPN-only)** — smaller attack surface, but rejected in favor of convenience:
  operator explicitly chose public Ingress + role restriction over
  internal-only access.
- **Fold Longhorn's UI auth into the existing `aii-longhorn` Application as
  chart-owned resources** — rejected: `longhorn/longhorn`'s upstream chart has
  no oauth2-proxy/ingress concept of its own, and bolting one on via
  post-render patches would fight the chart on every upgrade. A separate,
  dedicated Application (the established pattern for every other
  no-native-auth UI in this repo) is cleaner and matches precedent.

## Related

- Builds on: [0092](./0092-longhorn-for-hetzner-gpu-nodes.md) (the Longhorn
  deployment this gates), [0089](./0089-homepage-central-hub-oauth2-proxy.md)
  (the reverse-proxy-mode pattern this mirrors), [0085](./0085-mlops-platform-lakefs-argo-workflows-mlflow.md)
  (the multivalued-claim lesson), [0018](./0018-umbrella-apps-and-env-overlays.md)
  (deps-overlay/umbrella conventions), [0055](./0055-oci-charts-and-image-updater-writeback-to-values-repo.md)/[0056](./0056-workload-values-in-ai-helm-values.md)
  (continuous delivery + values-repo split).
- Charts/files touched: `charts/longhorn-auth/` (new orchestrator),
  `charts/longhorn-secrets/` (new leaf), `charts/apps/values.yaml`
  (`aii-longhorn-auth` entry), `charts/keycloak-baseline/values.yaml`
  (`longhorn-proxy` client + `longhorn_roles` scope — **manual realm change
  required**, see the PR description), `ai-helm-values`
  `environments/prod/values/longhorn-auth.yaml`,
  `environments/{base,prod}/deps/longhorn-auth/`.
