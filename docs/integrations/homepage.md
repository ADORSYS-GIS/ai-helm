# Homepage — the central hub

**ADR:** [0089](../adr/0089-homepage-central-hub-oauth2-proxy.md)
**Orchestrator:** [`charts/homepage`](../../charts/homepage/) (namespace
`homepage`)

[Homepage](https://gethomepage.dev) is the platform's central-hub dashboard —
`https://hub.ai.camer.digital`, gated by a dedicated `oauth2-proxy` (Homepage
itself has no login of its own). Content is **hybrid**: hand-curated tiles
(`environments/prod/values/homepage-app.yaml` in `ai-helm-values`,
`homepage.configMaps.content.data."services.yaml"`/`"bookmarks.yaml"` —
bjw-template v4's native `configMaps:` block, no custom chart templates)
plus k8s auto-discovery via annotations on existing Ingress/HTTPRoute
resources.

## Adding a new app to the hub (auto-discovery)

Add these annotations to the app's **existing** Ingress (or HTTPRoute — the
`homepage` ServiceAccount's ClusterRole covers both `networking.k8s.io`
Ingresses and `gateway.networking.k8s.io` HTTPRoutes/Gateways):

```yaml
annotations:
  gethomepage.dev/enabled: "true"
  gethomepage.dev/name: "My App"
  gethomepage.dev/group: "Some Group"       # tiles are grouped by this
  gethomepage.dev/icon: "myapp.png"          # https://github.com/walkxcode/dashboard-icons
```

That's it — no `charts/homepage-app` change needed. Homepage's k8s connector
(`kubernetes.yaml`, `mode: cluster`) re-scans on its own; a brand-new tile
shows up without a restart. A `services.yaml`/`bookmarks.yaml` content edit
(ai-helm-values `homepage.configMaps.content.data.*`) rolls the Deployment
automatically too — bjw-template v4's native `configMaps:` block computes a
`checksum/configMaps` pod annotation for you.

Current annotated set (as of 2026-09, via `gethomepage.dev/*` in ai-helm-values
`environments/**`): Grafana (Observability), MLflow & Argo Workflows & LakeFS
(MLOps), Coder (Dev Environments), LibreChat + "LibreChat (kivoyo redirect)"
(Chat), opencode well-known (Dev Tools), the Lightbridge Platform-API /
Code-Intelligence tiles, and Repo Auth (Platform APIs). Self-hosted inference
models are **not** auto-discovered — they are cluster-local (ADR-0095, no
Ingress/HTTPRoute to annotate) and instead surface as a curated "Models → AI
Gateway" tile (see below).

⚠️ **Icon tip:** a `gethomepage.dev/icon` value must name an existing file in
[walkxcode/dashboard-icons](https://github.com/walkxcode/dashboard-icons)
(e.g. `argo-cd.png`, **not** `argo.png`). A missing icon 404s on the CDN and the
tile renders blank/broken — verify the filename exists before annotating.

## When to use a curated tile instead

Reach for a curated tile (`homepage.configMaps.content.data."services.yaml"`/
`"bookmarks.yaml"` in ai-helm-values) instead of an annotation when the
target has **no in-cluster Ingress/HTTPRoute** to
annotate — an external link, a doc site, a status widget that isn't really
"about" any single app's Ingress (the "Platform" group's "Cluster Health"
tile), or (as with self-hosted models) a cluster-local service that is only
reachable through the gateway (the "Models" group's "AI Gateway" tile,
`https://api.ai.camer.digital`). Don't add BOTH an annotation and a curated
tile for the same app — that double-lists it.

## Status/uptime widgets

Homepage's `prometheus` widget on a service tile queries Mimir directly —
the same `http://mimir-nginx.observability.svc.cluster.local/prometheus`
URL Grafana's own datasource uses (`environments/prod/values/grafana.yaml`).
No new monitoring pipeline; this is the ADR-0089 decision. Requires the
`homepage-app-allow` `CiliumNetworkPolicy` (`environments/prod/deps/homepage/`)
to permit egress to `mimir-nginx` in the `observability` namespace — if you
add a widget pointing somewhere else in-cluster, you'll likely need to widen
that policy too.

## Auth

`homepage-auth` (an `oauth2-proxy` instance, reverse-proxy mode, own
Keycloak client `homepage-proxy`) is the sole gate — see ADR-0089 for why
this is *not* the redundant-second-login mistake ADR-0085 removed from
LakeFS. Secrets (`homepage_proxy_client_id`/`_client_secret`/`_cookie_secret`)
live in `ssegning-aws` `ai/camer/digital/prod/env`, provisioned out-of-band.
