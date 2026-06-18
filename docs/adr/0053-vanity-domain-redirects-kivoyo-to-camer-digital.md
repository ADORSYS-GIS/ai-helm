# ADR-0053: Redirect the `kivoyo.com` vanity hosts to their `camer.digital` canonicals

**Status:** Accepted
**Date:** 2026-06-18
**Deciders:** @stephane-segning

## Context

We own `kivoyo.com` and its DNS for `api.ai.kivoyo.com` and `ai.kivoyo.com`
already resolves to this cluster — `api.ai.kivoyo.com` to the Envoy AI Gateway
LoadBalancer, `ai.kivoyo.com` to the Traefik LoadBalancer (the same LBs that
serve the canonical `api.ai.camer.digital` / `ai.camer.digital`). The platform's
single source of truth for hostnames is `domainBase: ai.camer.digital`
(`environments/prod/cluster.yaml`); `camer.digital` is canonical. We want callers
of the kivoyo hosts to be **redirected** to the canonical hosts, not served two
parallel front-doors (which would split TLS, cookies, OIDC redirect URIs, and
per-user attribution across two origins).

The two hosts sit behind two different ingress stacks, so there is no single
place to express the redirect:

- `api.ai.kivoyo.com` terminates at the **Envoy AI Gateway** (`charts/core-gateway`),
  where TLS is issued by an in-chart ACME HTTP-01 Issuer that solves *through the
  Gateway's `:80` listener* and an existing `RequestRedirect` HTTPRoute already
  does HTTP→HTTPS for the api host.
- `ai.kivoyo.com` terminates at **Traefik** (`charts/librechat-app`, a bjw-template
  Ingress), where TLS comes from the `cert-home-cert-http` ClusterIssuer.

## Decision

Add **vanity-domain redirects** at each host's own ingress layer. Redirects are
**temporary** (so kivoyo can later be promoted to a first-class domain without
fighting browser/client caches of a permanent redirect) and **path + query
preserving**.

- **API host (Envoy AI Gateway).** Generalize the single-host HTTP→HTTPS redirect
  into a reusable `gateway.redirectHosts` list on `charts/core-gateway`. Each
  entry (`{name, from, to, statusCode}`) renders: a dedicated HTTPS `Terminate`
  listener for `from` (`templates/gateway.yaml`), an ACME `Certificate` for `from`
  reusing the same issuer logic as the api host (`templates/redirect-hosts.yaml`),
  and an `HTTPRoute` attached to **both** the `:80` `http` listener and the new
  per-host HTTPS listener carrying a `RequestRedirect` filter (`scheme: https`,
  `hostname: <to>`, no path modifier). Wired in `charts/apps`:
  `api.ai.kivoyo.com → api.ai.camer.digital`, **`307`** (temporary, preserves
  method/body — it's an API).
- **Web host (Traefik).** Add two `librechat.rawResources` on `charts/librechat-app`:
  a Traefik `redirectRegex` **Middleware** (`kivoyo-redirect`, `permanent: false`
  → `302`) rewriting `^https?://ai\.kivoyo\.com/(.*)` →
  `https://ai.camer.digital/${1}`, and a dedicated **Ingress** for `ai.kivoyo.com`
  (`className: traefik`, TLS via `cert-home-cert-http`, the middleware referenced
  by the `traefik.ingress.kubernetes.io/router.middlewares` annotation). The
  Ingress backend points at the `librechat-app` Service but is never reached (the
  middleware `302`s first); the spec just requires a backend.

Both certs are issued by the existing ACME machinery (no new issuer, no DNS
token) precisely because the kivoyo DNS already points at these LBs.

## Consequences

**Positive**
- One canonical origin. TLS, cookies, OIDC redirect URIs, rate-limit/attribution
  all stay on `camer.digital`; kivoyo is a thin doormat.
- The Envoy mechanism is generic: any future vanity host is one `redirectHosts`
  entry, no new templates.
- Zero behaviour change when unused — `redirectHosts` defaults to `[]`.

**Negative**
- `307`/`302` are *not cached*, so every kivoyo hit pays a round-trip + the
  redirect. Acceptable for a vanity alias; revisit (→ `308`/`301`) only if kivoyo
  becomes high-traffic and is confirmed permanent.
- Two more public ACME certs to keep renewed (Let's Encrypt rate limits apply).

**Neutral / follow-ups**
- ACME-safe by path precedence: cert-manager's exact
  `/.well-known/acme-challenge/<token>` out-ranks the redirect's `/` prefix on
  both Envoy (Gateway-API longest-match) and Traefik (router priority by rule
  length). Verify on first sync; if Traefik ever serves the challenge through the
  redirect, exclude that path from the regex.
- Adding rawResources to `librechat-app` pushed the rawResource count past 1, so
  the pre-existing HPA is pinned with `forceRename` to keep its name stable
  (bjw-template appends the identifier once >1 rawResource exists).
- Deploy is tag-based (never `main`): ship via `tools/release.sh` + the home-os
  root repoint.

## Alternatives considered

- **Serve LibreChat / the gateway directly on the kivoyo hosts (no redirect)** —
  rejected: two live origins fork TLS, session cookies, OIDC `redirect_uri`
  allow-lists, and per-user attribution; double the operational surface for a
  domain we only want as an alias.
- **Permanent redirect (`308`/`301`)** — rejected for now: hard browser/CDN
  caching makes it painful to repurpose kivoyo later. Temporary keeps the option
  open (the user's explicit choice).
- **DNS/CDN-level redirect (e.g. Cloudflare page rule)** — rejected: keeps the
  redirect contract out of GitOps; we already terminate these hosts in-cluster,
  so expressing it in the charts keeps one source of truth.
- **A single Traefik redirect for both hosts** — impossible: `api.ai.kivoyo.com`
  doesn't resolve to Traefik, it resolves to the Envoy Gateway LB.

## Related

- Charts/files touched: `charts/core-gateway/values.yaml`,
  `charts/core-gateway/templates/gateway.yaml`,
  `charts/core-gateway/templates/redirect-hosts.yaml` (new),
  `charts/apps/values.yaml`, `charts/librechat-app/values.yaml`
- Builds on: the in-chart ACME HTTP-01 + HTTP→HTTPS redirect pattern
  (`charts/core-gateway/templates/{acme-issuer,certificate,https-redirect-route}.yaml`),
  ADR-0014 (librechat split), ADR-0017 (gateway destinations)
- Docs: `docs/architecture.md`, `docs/arc42.md` §5/§9
