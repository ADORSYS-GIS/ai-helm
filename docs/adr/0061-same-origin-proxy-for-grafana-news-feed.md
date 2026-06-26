# ADR-0061: Same-origin Caddy proxy for the scoreboard's Grafana news feed

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

Serve the Atom feed **same-origin with Grafana** via a tiny in-cluster **Caddy**
reverse-proxy (`charts/governance-feed-proxy`), exposed at a path on the existing
Grafana host (`https://grafana.<domain>/_governance.atom`) by a second Traefik
Ingress. The browser then fetches the feed from the **same origin** as the
Grafana app — **no CORS at all**, and it reuses Grafana's TLS (no new
hostname/cert). The news panel's `feedUrl` points at that path.

Shape (reuses the ADR-0040 Caddy pattern — off-the-shelf `caddy:2-alpine`, no
custom image):

- **Caddy Deployment + Service + Caddyfile ConfigMap** in `observability`. The
  Caddyfile `reverse_proxy https://github.com` with `header_up Host github.com`;
  Caddy's Go TLS handles the upstream.
- **`rewrite * <fixed feed path>`** — every incoming request, whatever its URL, is
  rewritten to the one governance feed path. So this is **not an open proxy**: it
  can only ever return that single feed. Egress is *additionally* pinned to
  `github.com` by the deps-overlay `CiliumNetworkPolicy`.
- **Second Traefik Ingress** on `grafana.<domain>`, path `/_governance.atom` →
  the Caddy Service. Traefik routes the more-specific path to Caddy and
  everything else to Grafana; TLS reuses the host's existing cert.
- **deps overlay** (`environments/prod/deps/governance-feed-proxy`, ai-helm-values):
  the `CiliumNetworkPolicy` — egress to `github.com:443` (+ L7 DNS) and ingress
  from the `traefik` namespace — since `observability` is default-deny both ways.

## Consequences

- The live, auto-updating governance news panel works, with no CORS and no new
  public hostname or certificate.
- One small standing component (a Caddy pod + Service + Ingress + netpol) for a
  single dashboard widget. Accepted as proportionate to keeping the live feed;
  the alternative (a static links panel) remains a one-line fallback if it's ever
  not worth the upkeep.
- The proxy is locked to one upstream path **and** one egress FQDN (defence in
  depth) — it cannot be repurposed as an open proxy.
- ⚠️ The feed URL baked into the generated dashboard JSON is the **prod Grafana
  host** (env-specific, like the datasource UIDs). A second environment overrides
  `ingress.host` (chart value) and the `GOVERNANCE_NEWS_FEED` generator constant.
- The `github.com` egress on **Grafana's** own `CiliumNetworkPolicy` was removed
  (it was never used — the fetch is client-side, then proxied via Traefik→Caddy;
  Grafana itself never calls GitHub).
