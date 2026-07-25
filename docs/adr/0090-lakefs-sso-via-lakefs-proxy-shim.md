# ADR-0090: Keycloak SSO for LakeFS via the `lakefs-proxy` session shim

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** @stephane-segning

Amends [ADR-0085](0085-mlops-platform-lakefs-argo-workflows-mlflow.md)'s LakeFS
auth decision (the ADR body stays as written — ADRs are immutable once
Accepted). ADR-0085 shipped LakeFS behind a plain `oauth2-proxy`; that child was
then removed ([#755](https://github.com/adorsys-gis/ai-helm/pull/755)) and a
native-OIDC attempt was reverted ([#757](https://github.com/adorsys-gis/ai-helm/pull/757)).
This ADR records the shape that actually works.

Runbook + troubleshooting: [`docs/playbooks/lakefs-sso.md`](../playbooks/lakefs-sso.md).

## Context

Three things about LakeFS OSS were established **by live verification**, not by
reading docs, and they bound every option:

1. **LakeFS OSS 1.83 has no built-in OIDC.** Setting the `auth.oidc.*` keys makes
   the binary **fatal-error at startup** — it does not ignore them:

   ```
   error: 'auth.oidc' has invalid keys: callback_base_url, client_id, enabled, url
   error: 'auth.ui_config' has invalid keys: login_url_method
   ```

   The page `docs.lakefs.io/security/authentication/#oidc-support` documents an
   **older** lakeFS. In 1.83 the OIDC provider moved to `auth.providers.oidc`,
   which is Enterprise-only (the closed-source "Fluffy" service). That is what
   killed the native-OIDC attempt (#756, reverted in #757).
2. **A plain oauth2-proxy in front of LakeFS is not SSO.** It authenticates the
   browser against Keycloak, but LakeFS cannot consume that identity, so the
   user still meets LakeFS's own access-key login form behind the Keycloak one.
   That is precisely why the original `lakefs-auth` child was removed in #755 —
   the removal reasoning was correct *for a bare proxy*.
3. **LakeFS OSS with `auth.ui_config.rbac: none` is SINGLE-USER.** It cannot
   provision additional users. Proven twice, live:
   - the **remote-authenticator** path logged
     `first time remote authenticated user, creating them` and then failed
     `create backing user for remote auth user alice: failed to create user (alice): already exists`
     — and the user list still showed only `admin`;
   - `lakefs superuser --user-name <any-new-name>` fails `already exists` for
     **any** name.

   ACLs were removed from core lakeFS; real per-user identity needs the external
   `contrib/auth/acl` server (which has **no published image**) or Enterprise.

So the choice was never "per-user LakeFS identity vs. shared" — OSS only offers
shared. The real question was whether the *front door* can be a Keycloak login
instead of a shared access key pasted into a form.

A local docker-compose spike validated a shape end-to-end, including a real
browser login, and it was then confirmed live on the cluster:

```
browser → oauth2-proxy (Keycloak OIDC redirect) → lakefs-proxy → LakeFS
```

`lakefs-proxy` is a small Rust/axum service ([`adorsys-gis/lakefs-proxy`](https://github.com/adorsys-gis/lakefs-proxy),
image `ghcr.io/adorsys-gis/lakefs-proxy`, private, ~10.7 MB distroless, non-root
65532, listens on 8080, `/healthz`). oauth2-proxy authenticates the human and
forwards `X-Auth-Request-Email`. The shim sees an authenticated request carrying
no `internal_auth_session` cookie, POSTs to LakeFS `/api/v1/auth/login` as the
bootstrap admin, **relays LakeFS's own `Set-Cookie` verbatim** back to the
browser, 302s, and from then on transparently reverse-proxies.

**The cookie relay is the load-bearing detail.** `internal_auth_session` is a Go
`gorilla/securecookie` value — `<timestamp>|<gob-encoded data>|<hmac>` — **not a
JWT**. It cannot be hand-minted by a third party, so the shim must obtain a real
one from LakeFS and pass it through. Interesting corollary, proven live: a
hand-minted **HS256 JWT** signed with `auth.encrypt.secret_key` **does** work as
an `Authorization: Bearer` token against the LakeFS API, but is **rejected** as
the session cookie. Two different verifiers; only the API one accepts a JWT.

## Decision

**Add a third hop.** LakeFS is fronted by `lakefs-auth` (oauth2-proxy,
reverse-proxy mode) → `lakefs-proxy` (the shim) → `lakefs`.

- **New leaf chart `charts/lakefs-proxy`** — bjw-template-native (Deployment +
  ClusterIP Service, port 80 → container 8080, probes on `/healthz`, non-root,
  read-only rootfs, no ServiceAccount token). It owns no ingress; its only
  client is `lakefs-auth`, in-cluster. Its image is a **private** GHCR package,
  so it pulls with a namespace-local dockerconfigjson (`lakefs-ghcr`) via bjw's
  `defaultPodOptions.imagePullSecrets`.
- **Shim interface** (all env, no config file): `LAKEFS_URL`,
  `LAKEFS_ADMIN_ACCESS_KEY_ID`, `LAKEFS_ADMIN_SECRET_ACCESS_KEY`,
  `LISTEN_ADDR`, `RUST_LOG`. The two credential vars are rendered
  **`optional: false`** on purpose — an optional `secretKeyRef` binds once at
  pod start, so a pod that beats ESO would capture an empty credential and 502
  forever (the context7 `MCP_TOKEN` incident).
- **Loop guard.** The shim appends `_lakefs_sso=1` to its 302 target. If a
  request comes back still cookie-less **with** that marker, it returns a **503**
  carrying a human-readable message instead of redirecting forever. Once the
  cookie does arrive it issues one clean-up 302 to the de-markered URL, so the
  marker never sticks in the address bar.
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
  is **not reconciled on-cluster** — no ArgoCD app, no keycloak-config-cli, no
  `KeycloakRealmImport` CR — so the live client must be adjusted **by hand**, and
  the live client id is `lakefs_proxy` (**underscores**; the chart's hyphenated
  name never matched anything live).
- **Two new secrets**: `lakefs-proxy-secret` (oauth2-proxy client-id/secret/
  cookie-secret, restored) and `lakefs-proxy-admin` (the LakeFS bootstrap admin
  access-key/secret the shim logs in with).

## Consequences

- **Authentication is genuinely per-Keycloak-user.** Access requires a valid
  Keycloak login — verified live: a wrong password and an unknown user are both
  rejected at Keycloak, never reaching LakeFS. Nobody needs a LakeFS access key,
  and revoking a Keycloak user revokes LakeFS access.
- **⚠️ In-LakeFS authorization and audit are SHARED.** Every SSO user operates as
  the one `admin` LakeFS identity — **all commits appear as `admin`**. LakeFS's
  own audit trail attributes every action to `admin`; there is no in-LakeFS
  per-user permission boundary. This is an accepted, documented limitation of
  LakeFS OSS, not of this design — closing it requires LakeFS Enterprise or
  replacing LakeFS. **Do not treat LakeFS as a per-user-authorized system.** The
  oauth2-proxy access log (and the shim's own logs, which carry the
  `X-Auth-Request-Email`) remain the only per-person record of who used it.
- **The `admin` access key becomes a platform credential.** It lives in one
  place (`lakefs_admin_access_key_id` / `lakefs_admin_secret_access_key` in
  `ssegning-aws`) and rotating it means updating those two properties, not
  re-keying users. ⚠️ `lakefs superuser` **creates** an admin and prints its
  key pair **once** — it is not a reset; recovery when the credential is lost is
  a destructive KV wipe, only safe while LakeFS holds no repositories. Runbook:
  [`docs/playbooks/lakefs-sso.md`](../playbooks/lakefs-sso.md#runbook--rotate-or-recover-the-lakefs-admin-credential).
- **One more hop to debug.** A 502 at the front door can now come from three
  places. The chain is explicit in the CiliumNetworkPolicies, and Cilium
  enforces on **container** ports: `lakefs-auth → lakefs-proxy:8080` and
  `lakefs-proxy → lakefs:8000` (both Services publish :80).
- **A first-party image enters the deployment path.** `lakefs-proxy` is our own
  code, private on GHCR, so `mlops` now needs a pull credential it did not need
  before, and the image is a supply-chain item this repo does not build. ⚠️ It
  must be built with **`cargo-auditable`** — without it Trivy scans **zero**
  Rust crates (only the base OS) and a green scan is meaningless. With it, Trivy
  reports a `rustbinary` target (110 packages for this image).

## Alternatives considered

- **LakeFS native OIDC (`auth.oidc.*`).** Rejected — not merely undocumented but
  **fatally rejected** by the OSS binary's config validator at startup
  (attempted in #756, reverted in #757). The provider is `auth.providers.oidc`
  in 1.83 and is Enterprise-only.
- **Bare oauth2-proxy, no shim.** Rejected — double login, no LakeFS session.
  This is the exact shape removed in #755.
- **Provision one LakeFS user per Keycloak user from the shim.** Rejected — not
  possible: LakeFS OSS with `rbac: none` refuses to create users (verified two
  ways; see Context).
- **LakeFS's Remote Authenticator Service extension point.** Tried and rejected —
  the endpoint is reached and LakeFS does attempt the provisioning
  (`first time remote authenticated user, creating them`), but the backing-user
  creation fails `already exists` because OSS only has the one user. It is an
  Enterprise-shaped extension point on an OSS binary that cannot honour it.
- **The `contrib/auth/acl` server** (the out-of-tree replacement for the ACLs
  removed from core lakeFS). Rejected — no published image, so we would own
  building and maintaining a second first-party component to get a permission
  model LakeFS itself no longer ships.
- **Mint the LakeFS session cookie ourselves.** Rejected — it's a Go
  `securecookie` (`<timestamp>|<gob>|<hmac>`), not a JWT; it must come from
  LakeFS. (A hand-minted HS256 JWT works as a Bearer *API* token but is rejected
  as the cookie — so it cannot log a *browser* in.)
- **An OpenResty/Lua shim instead of a Rust service.** Proven to work (the same
  login-and-relay logic fits in a `rewrite_by_lua_block`, as in the ADR-0041
  firecrawl proxy). Rejected on **testability**: the Lua version lives as a
  string inside a ConfigMap — unrunnable in CI, untypeable, and untestable
  outside the cluster. This repo has already paid for logic-in-a-templated-
  ConfigMap once (the Alloy River config, whose Go-template braces broke ArgoCD
  manifest generation and passed every local gate — see `CLAUDE.md`). A compiled
  binary with unit tests and a real CI pipeline is worth the extra image.
- **Leave LakeFS on its native access-key login** (the #755 status quo).
  Rejected — it means distributing a shared access key out-of-band, with no
  Keycloak lifecycle at all. The shim gives the same shared LakeFS identity but
  behind real per-user authentication, which is strictly better.
- **LakeFS Enterprise / lakeFS Cloud.** Rejected — commercial, and out of scope
  for a self-hosted platform.

## Related

- ADRs: amends [0085](./0085-mlops-platform-lakefs-argo-workflows-mlflow.md);
  contrast [0089](./0089-homepage-central-hub-oauth2-proxy.md) (Homepage needs
  only the proxy — it has no login of its own, so no shim); the
  ConfigMap-logic lesson is [0046](./0046-per-user-attribution-otlp-envelope-repair.md)'s
  Alloy config.
- Playbooks: [`lakefs-sso.md`](../playbooks/lakefs-sso.md) (this shim),
  [`mlops-app-auth.md`](../playbooks/mlops-app-auth.md) (Argo Workflows + MLflow).
- Component: [`adorsys-gis/lakefs-proxy`](https://github.com/ADORSYS-GIS/lakefs-proxy)
  (Rust/axum), image `ghcr.io/adorsys-gis/lakefs-proxy` (private).
- Charts: `charts/lakefs-proxy/`, `charts/lakefs/`, `charts/lakefs-secrets/`,
  `charts/keycloak-baseline/`.
- `ai-helm-values`: `environments/prod/values/{lakefs-proxy,lakefs-auth,lakefs-app}.yaml`,
  `environments/{base,prod}/deps/lakefs/`.
