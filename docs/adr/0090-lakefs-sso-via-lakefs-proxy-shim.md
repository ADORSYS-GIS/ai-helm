# ADR-0090: Keycloak SSO for LakeFS via the `lakefs-proxy` session shim

**Status:** Proposed
**Date:** 2026-07-25
**Deciders:** @stephane-segning

Amends [ADR-0085](0085-mlops-platform-lakefs-argo-workflows-mlflow.md)'s LakeFS
auth decision (the ADR body stays as written — ADRs are immutable once
Accepted). ADR-0085 shipped LakeFS behind a plain `oauth2-proxy`; that child was
then removed ([#755](https://github.com/adorsys-gis/ai-helm/pull/755)) and a
native-OIDC attempt was reverted ([#757](https://github.com/adorsys-gis/ai-helm/pull/757)).
This ADR records the shape that actually works.

## Context

Three things about LakeFS OSS were established **by live verification**, not by
reading docs, and they bound every option:

1. **LakeFS OSS 1.83 has no built-in OIDC.** The `auth.oidc.*` provider keys are
   rejected outright at startup:
   `has invalid keys: enabled, client_id, url, callback_base_url`. That provider
   is Enterprise-only ("Fluffy"). This is what killed the native-OIDC attempt
   (#756, reverted in #757).
2. **A plain oauth2-proxy in front of LakeFS is not SSO.** It authenticates the
   browser against Keycloak, but LakeFS cannot consume that identity, so the
   user still meets LakeFS's own access-key login form behind the Keycloak one.
   That is precisely why the original `lakefs-auth` child was removed in #755 —
   the removal reasoning was correct *for a bare proxy*.
3. **LakeFS OSS with `rbac: none` is single-user.** Verified live: it refuses to
   create additional users; only `admin` exists. There is no OSS path to
   per-user LakeFS identities at all, with or without SSO.

So the choice was never "per-user LakeFS identity vs. shared" — OSS only offers
shared. The real question was whether the *front door* can be a Keycloak login
instead of a shared access key pasted into a form.

A local docker-compose spike validated a shape end-to-end, including a real
browser login:

```
browser → oauth2-proxy (Keycloak OIDC redirect) → lakefs-proxy → LakeFS
```

`lakefs-proxy` is a small Rust service ([`adorsys-gis/lakefs-proxy`](https://github.com/adorsys-gis/lakefs-proxy),
image `ghcr.io/adorsys-gis/lakefs-proxy`, private). oauth2-proxy authenticates
the human and forwards `X-Auth-Request-Email`. The shim sees an authenticated
request carrying no `internal_auth_session` cookie, logs into LakeFS as the
bootstrap admin over the LakeFS API, **relays LakeFS's own `Set-Cookie`** back
to the browser, 302s, and from then on transparently reverse-proxies.

The cookie relay is the load-bearing detail: LakeFS's session cookie is a Go
`securecookie` value, **not** a JWT — it cannot be hand-minted by a third party,
so the shim must obtain a real one from LakeFS and pass it through.

## Decision

**Add a third hop.** LakeFS is fronted by `lakefs-auth` (oauth2-proxy,
reverse-proxy mode) → `lakefs-proxy` (the shim) → `lakefs`.

- **New leaf chart `charts/lakefs-proxy`** — bjw-template-native (Deployment +
  ClusterIP Service, port 80 → container 8080, probes on `/healthz`, non-root,
  read-only rootfs, no ServiceAccount token). It owns no ingress; its only
  client is `lakefs-auth`, in-cluster. Its image is a **private** GHCR package,
  so it pulls with a namespace-local dockerconfigjson (`lakefs-ghcr`) via bjw's
  `defaultPodOptions.imagePullSecrets`.
- **`charts/lakefs` gains a `proxy` child and re-enables `auth`.** Waves:
  `lakefs-secrets` 0 → `lakefs-app` 2 → `lakefs-proxy` 3 → `lakefs-auth` 4
  (front door last, once its upstream chain exists).
- **oauth2-proxy's `--upstream` is the shim**
  (`http://lakefs-proxy.mlops.svc.cluster.local:80`), never LakeFS directly.
  `--set-xauthrequest=true` is mandatory: the shim keys off
  `X-Auth-Request-Email`.
- **The LakeFS chart owns no ingress** (`ingress.enabled: false`). The single
  front-door Ingress for `lakefs.mlops.ai.camer.digital` lives in the deps
  overlay and points at the oauth2-proxy Service. A chart-owned ingress would
  publish a second, unauthenticated route straight past the gate.
- **The `lakefs-proxy` Keycloak client is restored** in
  `charts/keycloak-baseline` (confidential, standard flow, redirect
  `https://lakefs.mlops.ai.camer.digital/oauth2/callback`). ⚠️ That realm config
  is not reconciled on-cluster today — the live client must be adjusted by hand.
- **Two new secrets**: `lakefs-proxy-secret` (oauth2-proxy client-id/secret/
  cookie-secret, restored) and `lakefs-proxy-admin` (the LakeFS bootstrap admin
  access-key/secret the shim logs in with).

## Consequences

- **Authentication is genuinely per-Keycloak-user.** Access requires a valid
  Keycloak login; nobody needs a LakeFS access key, and revoking a Keycloak user
  revokes LakeFS access.
- **⚠️ In-LakeFS authorization and audit are SHARED.** Every SSO user operates as
  the one `admin` LakeFS identity. LakeFS's own audit trail attributes every
  action to `admin`; there is no in-LakeFS per-user permission boundary. This is
  an accepted, documented limitation of LakeFS OSS, not of this design — closing
  it requires LakeFS Enterprise or replacing LakeFS. **Do not treat LakeFS as a
  per-user-authorized system.** The oauth2-proxy access log (and the shim's own
  logs) remain the only per-person record of who used it.
- **The `admin` access key becomes a platform credential.** It lives in one
  place (`lakefs_admin_*` in `ssegning-aws`) and rotating it means updating
  those two properties, not re-keying users.
- **One more hop to debug.** A 502 at the front door can now come from three
  places. The chain is explicit in the CiliumNetworkPolicies, and Cilium
  enforces on **container** ports: `lakefs-auth → lakefs-proxy:8080` and
  `lakefs-proxy → lakefs:8000` (both Services publish :80).
- **A first-party image enters the deployment path.** `lakefs-proxy` is our own
  code, private on GHCR, so `mlops` now needs a pull credential it did not need
  before, and the image is a supply-chain item this repo does not build.

## Alternatives considered

- **LakeFS native OIDC (`auth.oidc.*`).** Rejected — not merely undocumented but
  actively rejected by the OSS binary's config validator (attempted in #756,
  reverted in #757).
- **Bare oauth2-proxy, no shim.** Rejected — double login, no LakeFS session.
  This is the exact shape removed in #755.
- **Provision one LakeFS user per Keycloak user from the shim.** Rejected — not
  possible: LakeFS OSS with `rbac: none` refuses to create users (verified).
- **Mint the LakeFS session cookie ourselves.** Rejected — it's a Go
  `securecookie`, not a JWT; it must come from LakeFS.
- **Leave LakeFS on its native access-key login** (the #755 status quo).
  Rejected — it means distributing a shared access key out-of-band, with no
  Keycloak lifecycle at all. The shim gives the same shared LakeFS identity but
  behind real per-user authentication, which is strictly better.
- **LakeFS Enterprise / lakeFS Cloud.** Rejected — commercial, and out of scope
  for a self-hosted platform.
