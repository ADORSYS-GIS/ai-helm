# ADR-0089: Homepage central hub, gated by a dedicated oauth2-proxy

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** @stephane-segning

## Context

The platform has grown to a dozen-plus user-facing apps (LibreChat, Coder,
LakeFS, MLflow, Argo Workflows, Grafana, model-serving endpoints, MCPs...)
each on its own hostname, with no shared entry point. [Homepage](https://gethomepage.dev)
(`ghcr.io/gethomepage/homepage`) was chosen as a central-hub dashboard:
config-driven (YAML), stateless single container, with native Kubernetes
service-discovery (Ingress/HTTPRoute annotations) and per-service status
widgets (including a `prometheus` widget type).

Homepage ships **no authentication of its own** — it is a pure
config-driven dashboard, unlike every other app this ADR's sibling
[ADR-0085](0085-mlops-platform-lakefs-argo-workflows-mlflow.md) covered
(LakeFS/Argo Workflows/MLflow all have *some* login story, even if imperfect).
That makes it the textbook case for a fronting `oauth2-proxy`. This repo
already built and later removed exactly that shape for LakeFS
([#755](https://github.com/adorsys-gis/ai-helm/pull/755)) — but the removal
reason was that LakeFS *already has its own native access-key login*, so the
proxy stacked a redundant second gate with no per-user benefit. Homepage has
no native login to be redundant with, so this is the case the pattern was
built for, not an instance of the mistake that got LakeFS's copy removed.

Content mode (co-designed with the maintainer): **hybrid** — curated
bookmarks/tiles for things with no in-cluster Ingress, plus k8s
auto-discovery via `gethomepage.dev/*` Ingress/HTTPRoute annotations for
everything else, so new apps opt in without a Homepage chart change.
Uptime/status: **reuse the existing Grafana/Mimir observability stack**
(the same `http://mimir-nginx.observability.svc.cluster.local/prometheus`
URL Grafana's own datasource already queries) via Homepage's native
`prometheus` widget — no new polling pipeline, no Uptime Kuma.

## Decision

Add `charts/homepage` as a new App-of-Apps orchestrator (ADR-0019 pattern,
own namespace `homepage`), with three children:

1. **`homepage-secrets`** (wave 0) — ExternalSecrets leaf chart: the
   `homepage-proxy-secret` (Keycloak client-id/secret + oauth2-proxy
   cookie-signing secret), own instance, not shared with any other app's
   oauth2-proxy.
2. **`homepage-auth`** (wave 1) — upstream `oauth2-proxy` chart (classic
   Helm repo, pinned `10.7.0` — same version the removed `lakefs-auth`
   used), reverse-proxy mode (`provider: keycloak-oidc`, `upstream:
   http://homepage.homepage.svc.cluster.local:3000`, `reverse-proxy: true`).
   No chart-owned ingress — the depsOverlay Ingress owns the front door and
   routes the whole hostname to this Service.
3. **`homepage-app`** (wave 2) — new local leaf chart `charts/homepage-app`,
   OCI-floated like every other in-repo chart. Entirely `bjw-template`-native
   (bjw-s app-template v4, no custom templates): the Deployment/Service, the
   ServiceAccount, and the read-only ClusterRole/ClusterRoleBinding Homepage's
   k8s discovery needs (upstream's own documented shape,
   gethomepage.dev/installation/k8s/ — `get`/`list` only, on
   `namespaces`/`pods`/`nodes`/`ingresses`/`httproutes`+`gateways`) all come
   from bjw v4's own declarative `serviceAccount:`/`rbac:` blocks, and the
   `/app/config` content ConfigMap from its native `configMaps:` block.

A new Keycloak client `homepage-proxy` (`charts/keycloak-baseline`) — unlike
the removed `lakefsProxy`, no custom clientScope/role mapper, since
oauth2-proxy here is a pure network gate with no per-role behavior.

Content (bookmarks/services/widgets) lives in `ai-helm-values`
(`environments/prod/values/homepage-app.yaml`, ADR-0056) — chart defaults
are empty stubs so the chart renders cleanly in CI with no override.

## Consequences

**Positive**
- One documented convention (`gethomepage.dev/*` annotations) lets any
  future app opt into the hub with a one-line Ingress annotation change —
  no Homepage chart/values change needed.
- No new polling/monitoring pipeline — the uptime widget reuses the
  observability stack that already exists.
- Homepage's own namespace + self-contained `CiliumNetworkPolicy` (its own
  `kube-system:53` DNS-allow rule, same as `lakefs-app-allow`/
  `lakefs-auth-allow`) needs no out-of-band `hetzner-k8s` baseline-netpol
  change — precedent: `mlops` (ADR-0085) needed none either.

**Negative**
- A cross-namespace `CiliumNetworkPolicy` egress rule to `mimir-nginx`
  (observability namespace) is new surface under the default-deny baseline;
  its label selector (`app.kubernetes.io/component: nginx,
  app.kubernetes.io/instance: mimir`) is mimir-distributed's standard
  convention but was **not** rendered/verified from this repo (upstream
  chart dependency) — needs a live check at first sync.
- Two-repo change (this repo + the private `ai-helm-values`), same
  paired-PR discipline ADR-0085/ADR-0056 already established — the
  values-repo PR must land first or `ignoreMissingValueFiles` silently
  falls back to chart defaults.
- The starter discovery-annotation set (Grafana, MLflow, Argo Workflows,
  Coder) is intentionally partial, not a full sweep — remaining apps
  (LibreChat, model-serving endpoints, MCPs) are annotated incrementally,
  each a one-line change per `docs/integrations/homepage.md`.

**Neutral / follow-ups**
- The Mimir `prometheus` widget query (`count(up == 1)` style) is a
  deliberately generic placeholder — tune to project-specific queries
  (gateway request rate, ArgoCD sync health, ...) once live.
- `homepage_proxy_client_id` / `homepage_proxy_client_secret` /
  `homepage_proxy_cookie_secret` need adding to `ssegning-aws`
  `ai/camer/digital/prod/env` out-of-band before first sync.

## Alternatives considered

- **No auth, rely on network-level obscurity** — rejected: the hub
  aggregates links/status for every app on the platform, including
  internal-only ones; it's exactly the kind of resource that should sit
  behind SSO, not "security by not linking it anywhere."
- **Route Homepage through the existing AI-Gateway Authorino AuthConfig**
  (ADR-0021) instead of a dedicated oauth2-proxy — rejected: Authorino
  verifies a bearer token that's already present (the API/service-to-service
  case); it doesn't perform the browser-facing OIDC Authorization Code
  redirect-to-login flow a human hitting a dashboard in a browser needs.
  oauth2-proxy is built for exactly that browser flow.
- **Share an existing oauth2-proxy instance** (e.g. if one still existed
  for another app) — rejected on the same grounds ADR-0085 used for
  LakeFS/MLflow: a shared proxy means a shared cookie/session domain and a
  shared blast radius if the client is compromised; a dedicated instance
  per app is the established pattern here.
- **Uptime Kuma (or similar) for status/uptime** — rejected: would be a
  second monitoring pipeline duplicating data already collected by
  Mimir/Alloy, plus its own polling egress-allow rules per target under the
  Cilium deny-baseline. Homepage's native `prometheus` widget reads the
  existing pipeline instead.
- **Full k8s-auto-discovery-only content mode** (no curated bookmarks) —
  rejected per the maintainer's explicit choice: less control over
  grouping/icons/ordering, and doesn't cover things with no in-cluster
  Ingress (external links, docs).

## Related

- Docs: `docs/integrations/homepage.md` (the discovery-annotation
  convention for future apps)
- Charts/files touched: `charts/homepage/`, `charts/homepage-secrets/`,
  `charts/homepage-app/`, `charts/apps/values.yaml`,
  `charts/keycloak-baseline/values.yaml`
- Builds on: [ADR-0018](0018-umbrella-apps-and-env-overlays.md) (deps
  overlay pattern), [ADR-0019](0019-coder-app-of-apps-orchestrator.md)
  (orchestrator pattern, canonical example),
  [ADR-0055](0055-oci-charts-and-image-updater-writeback-to-values-repo.md),
  [ADR-0056](0056-workload-values-in-ai-helm-values.md)
- Contrasts with: [ADR-0085](0085-mlops-platform-lakefs-argo-workflows-mlflow.md)
  (the LakeFS oauth2-proxy removal — the "already has native login"
  distinction this ADR turns on)
