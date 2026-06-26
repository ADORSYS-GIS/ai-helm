# ADR-0061: Generic same-origin Caddy proxy (`same-origin-proxy`)

**Status:** Accepted
**Date:** 2026-06-26
**Deciders:** @stephane-segning
**Amends (implementation of):** [ADR-0060](./0060-gamified-app-scoreboard.md) (the App Scoreboard's AI-governance panel)
**Relates to:** [ADR-0040](./0040-external-mcps-via-caddy-normalizing-proxy.md) (the Caddy in-cluster-proxy pattern this reuses)

## Context

ADR-0060's scoreboard has an **AI-governance news panel** pointed at the
governance repo's GitHub commits Atom feed (the MkDocs site has no RSS). It
rendered **"Error loading RSS feed … CORS"**.

Root cause: **Grafana's news panel fetches its feed client-side** — from the
viewer's browser, not the Grafana backend. GitHub's `.atom` returns `HTTP 200`
but sends **no `Access-Control-Allow-Origin` header**, so the browser
cross-origin fetch is blocked. This is **not** a pod-egress problem: verified the
Grafana pod reaches `github.com` fine (`HTTP 200`); the `github.com` egress that
was first added to Grafana's `CiliumNetworkPolicy` was therefore both unnecessary
and ineffective, and was removed.

So the original ADR-0060 rationale ("Grafana fetches it server-side → open
github.com egress") was wrong about the mechanism. Two ways forward were
considered for the panel and one was rejected outright:

- **Drop the news panel for a static text/links panel** — works, zero infra, but
  loses the live auto-updating feed.
- **Point the news panel at a CORS-enabled feed** — none exists for the
  governance repo; running a public *open* CORS proxy is an unnecessary surface.
- **Make the fetch same-origin** (chosen).

## Decision

Serve external resources **same-origin** via a small, **generic** in-cluster
**Caddy** reverse-proxy chart — **`charts/same-origin-proxy`** — exposed at paths
on an existing app's host by a second Traefik Ingress. The browser then fetches
each resource from the **same origin** as that app — **no CORS at all**, reusing
the host's TLS (no new hostname/cert). It is a reusable building block, not a
one-off: each `routes[]` entry maps a path to one upstream URL. First consumer:
the governance Atom feed at `https://grafana.<domain>/_governance.atom`, which the
scoreboard news panel's `feedUrl` points at.

Shape (reuses the ADR-0040 Caddy pattern — off-the-shelf `caddy:2-alpine`, no
custom image):

- **Caddy Deployment + Service + Caddyfile ConfigMap** (in `observability` for
  the first consumer). The Caddyfile renders **one `handle <path>` block per
  route** — `rewrite * <upstream.path>` then `reverse_proxy <scheme>://<host>`
  with `header_up Host <host>`; Caddy's Go TLS handles each upstream. An optional
  per-route `cors` adds `Access-Control-Allow-Origin` for the rare cross-origin
  reuse (same-origin routes need none).
- **`rewrite *`** pins every route to its one upstream path, so a route can only
  ever return that single resource — **not an open proxy**, regardless of request
  URL.
- **Second Traefik Ingress** on `ingress.host` with one path per route. Traefik
  routes the more-specific paths to Caddy and everything else to the host's main
  app; TLS reuses the host's existing cert.
- **In-chart `CiliumNetworkPolicy`** (NOT a deps overlay): egress `toFQDNs` is
  **derived from the distinct `routes[].upstream.host`** values (+ L7 DNS), and
  ingress is allowed from the Traefik namespace — since `observability` is
  default-deny both ways. Keeping it in-chart means adding a route opens its
  egress automatically, with no separate netpol file to keep in sync.
- **Config lives in ai-helm-values, not chart defaults** (ADR-0056/0057). The
  `charts/apps` entry uses OCI mode (`chart: same-origin-proxy`), so the template
  injects the `$values` ref reading
  `environments/<env>/values/same-origin-proxy.yaml` — the deployment-specific
  `ingress.host` / `tlsSecret` / `routes` come from there. Chart defaults are
  **empty** (a no-op render: no Ingress, no egress FQDNs); a `ci/lint-values.yaml`
  fixture (`lint-mode: ci-values`) gives CI a representative render. A second env
  is a sibling values file. The Pod runs hardened: non-root, `drop ALL`,
  read-only root FS (writable `emptyDir`s for Caddy `/data`,`/config`,`/tmp`),
  `automountServiceAccountToken: false`.

## Consequences

- The live, auto-updating governance news panel works, with no CORS and no new
  public hostname or certificate.
- One small standing component (a Caddy pod + Service + Ingress + netpol) for a
  single dashboard widget. Accepted as proportionate to keeping the live feed;
  the alternative (a static links panel) remains a one-line fallback if it's ever
  not worth the upkeep.
- The proxy is locked to one upstream path **and** one egress FQDN (defence in
  depth) — it cannot be repurposed as an open proxy.
- ⚠️ Two env-specific spots a second environment must set: the `ingress.host` /
  `routes` in `ai-helm-values` (`environments/<env>/values/same-origin-proxy.yaml`)
  and the `GOVERNANCE_NEWS_FEED` generator constant baked into the dashboard JSON
  (env-specific, like the datasource UIDs).
- The `github.com` egress on **Grafana's** own `CiliumNetworkPolicy` was removed
  (it was never used — the fetch is client-side, then proxied via Traefik→Caddy;
  Grafana itself never calls GitHub).
