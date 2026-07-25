# LakeFS Keycloak SSO — the `lakefs-proxy` session shim

**Live** at `https://lakefs.mlops.ai.camer.digital` (namespace `mlops`, cluster
`home-remote`). Decision + rejected alternatives: [ADR-0090](../adr/0090-lakefs-sso-via-lakefs-proxy-shim.md);
the surrounding MLOps platform: [ADR-0085](../adr/0085-mlops-platform-lakefs-argo-workflows-mlflow.md).
Argo Workflows + MLflow auth: [`mlops-app-auth.md`](./mlops-app-auth.md).

> **Read this first.** LakeFS OSS 1.83 has **no OIDC** and is **single-user**.
> Both facts are load-bearing and both are verified live — do not re-litigate
> them from the lakeFS docs site, which documents an older release. Setting
> `auth.oidc.*` **fatal-errors the binary at startup**; `auth.providers.oidc`
> (1.83's actual provider key) is Enterprise-only ("Fluffy"). With
> `auth.ui_config.rbac: none` LakeFS refuses to create a second user, so every
> SSO user shares the one `admin` identity.

## What SSO does and does not buy you

| | Status |
|---|---|
| **Authentication** | ✅ Genuinely per-Keycloak-user. A wrong password or unknown user is rejected by Keycloak and never reaches LakeFS. Revoking the Keycloak user revokes LakeFS access. No user ever handles a LakeFS access key. |
| **Authorization inside LakeFS** | ❌ **Shared.** Everyone is `admin`. There is no per-user permission boundary. |
| **Audit inside LakeFS** | ❌ **Shared.** Every commit, branch and merge is attributed to `admin`. |
| **Per-person record** | Only the oauth2-proxy access log and the shim's own logs (which carry `X-Auth-Request-Email`). |

**Do not treat LakeFS as a per-user-authorized system.** Closing the gap needs
LakeFS Enterprise or a different product — see ADR-0090's Alternatives.

## Architecture

```
                     TLS (Traefik ingress, deps overlay)
                                  │
                                  ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │  lakefs-auth        oauth2-proxy 10.7.0, reverse-proxy mode      │
  │  (wave 4)           provider keycloak-oidc → auth.verif.fyi      │
  │                     --set-xauthrequest=true                      │
  │                     cookie `_lakefs_proxy`                       │
  └──────────────────────────────┬───────────────────────────────────┘
                 authenticated + X-Auth-Request-Email
                                 ▼   (Service :80 → :8080)
  ┌──────────────────────────────────────────────────────────────────┐
  │  lakefs-proxy       Rust/axum shim, ghcr.io/adorsys-gis/…        │
  │  (wave 3)           no cookie?  → POST /api/v1/auth/login        │
  │                                    as the bootstrap admin        │
  │                                  → RELAY LakeFS's Set-Cookie     │
  │                                  → 302 …?_lakefs_sso=1           │
  │                     cookie?     → transparent reverse proxy      │
  └──────────────────────────────┬───────────────────────────────────┘
                                 ▼   (Service :80 → :8000)
  ┌──────────────────────────────────────────────────────────────────┐
  │  lakefs (wave 2)    upstream chart, ingress DISABLED             │
  │                     rbac: none · PG on lightbridge-main-db       │
  │                     blockstore: Hetzner Object Storage           │
  └──────────────────────────────────────────────────────────────────┘
```

`lakefs-secrets` (wave 0) materialises `lakefs-proxy-secret` (oauth2-proxy
client id/secret/cookie secret), `lakefs-proxy-admin` (the bootstrap admin key
pair) and `lakefs-ghcr` (the private-image pull credential) before any of it.

### Request flow

1. Browser hits `lakefs.mlops.ai.camer.digital/` → Traefik → **oauth2-proxy**.
2. No proxy session → 302 to Keycloak; user authenticates; callback at
   `/oauth2/callback`; oauth2-proxy sets `_lakefs_proxy` and proxies onward to
   its `--upstream`, **the shim**, adding `X-Auth-Request-Email`.
3. **Shim**: request is authenticated but carries no `internal_auth_session`
   cookie → POST `/api/v1/auth/login` to LakeFS with the bootstrap admin key
   pair → LakeFS answers with its own `Set-Cookie: internal_auth_session=…` →
   the shim **relays that header verbatim** and 302s to the same URL with
   `_lakefs_sso=1` appended.
4. Browser retries **with** the cookie → the shim strips the marker with one
   clean-up 302 and from then on is a transparent reverse proxy.
5. If the retry still has no cookie **and** carries `_lakefs_sso=1`, the shim
   **stops** — 503 with a readable message — instead of looping forever.

### Why the cookie must be relayed

`internal_auth_session` is a Go `gorilla/securecookie` value —
`<timestamp>|<gob-encoded data>|<hmac>` — **not a JWT**. It cannot be minted by
anything but LakeFS itself, which is the entire reason a shim exists rather than
a header-injecting proxy rule.

> Corollary, proven live: a hand-minted **HS256 JWT** signed with
> `auth.encrypt.secret_key` **is** accepted as an `Authorization: Bearer` token
> by the LakeFS **API**, but is **rejected** as the session cookie. Two
> different verifiers. The JWT path can script API calls; it cannot log a
> browser in.

## Config reference

| Knob | Value | Where |
|---|---|---|
| oauth2-proxy `--upstream` | `http://lakefs-proxy.mlops.svc.cluster.local:80` — **the shim, never LakeFS** | `ai-helm-values` `values/lakefs-auth.yaml`; reference copy `charts/lakefs/ci/lakefs-auth.yaml` |
| oauth2-proxy `--set-xauthrequest` | `true` — **mandatory**, the shim keys off `X-Auth-Request-Email` | same |
| oauth2-proxy `--reverse-proxy` | `true` (full proxy mode, not ForwardAuth) | same |
| oauth2-proxy secret | `lakefs-proxy-secret` (`config.existingSecret`) | `charts/lakefs-secrets` |
| `LAKEFS_URL` | `http://lakefs.mlops.svc.cluster.local:80` | `charts/lakefs-proxy/values.yaml` |
| `LAKEFS_ADMIN_ACCESS_KEY_ID` / `…_SECRET_ACCESS_KEY` | from Secret `lakefs-proxy-admin`, **`optional: false`** | same |
| `LISTEN_ADDR` / `RUST_LOG` | `0.0.0.0:8080` / `info` | same |
| Health | `GET /healthz` on 8080 (liveness + readiness) | same |
| Image | `ghcr.io/adorsys-gis/lakefs-proxy` — **private**, pulled via `lakefs-ghcr` in `defaultPodOptions.imagePullSecrets` | tag pinned in `ai-helm-values` |
| LakeFS ingress | `enabled: false` — the **only** front door is the deps-overlay Ingress → oauth2-proxy | `ai-helm-values` `values/lakefs-app.yaml` |
| Keycloak client | **`lakefs_proxy`** (underscores — see the drift warning below) | out-of-band, realm `camer-digital` |

Sync waves: `lakefs-secrets` 0 → `lakefs-app` 2 → `lakefs-proxy` 3 →
`lakefs-auth` 4. The front door goes up last, once there is something behind it.

⚠️ **Never re-enable the LakeFS chart's own ingress.** It would publish a second
route to LakeFS that bypasses oauth2-proxy entirely.

⚠️ **`cookie-secret` must decode to exactly 16, 24 or 32 bytes.** Generate it
with `openssl rand -hex 16` (32 characters). A padded base64 blob (44 chars)
fails at oauth2-proxy startup with
`cookie_secret must be 16, 24, or 32 bytes to create an AES cipher, but is 44 bytes`.

⚠️ **`charts/keycloak-baseline` is not reconciled by anything** — no ArgoCD app,
no keycloak-config-cli, no `KeycloakRealmImport`. Editing that chart does **not**
change the realm. The live client is `lakefs_proxy` with an underscore; the
chart's hyphenated `lakefs-proxy` never matched. Change Keycloak in the admin
console, then mirror it into the chart so the two do not drift further apart.

## The admin credential has a second consumer: Argo Workflows

`lakefs-proxy-admin` is not only the shim's login. Because LakeFS OSS with
`rbac: none` supports exactly **one** credential — its credential-management
API answers `501 Not Implemented` — any Argo Workflows step that talks to
LakeFS mounts *this same Secret*. It is deliberately not copied: a copy would
be a second rotation target and would hide the blast radius.

Two things follow:

- **Rotating it affects more than the shim.** A workflow pod picks up the new
  value on its next run, so workflows are self-healing here; the shim is not
  (its env binds once at pod start), which is why the runbook below ends with
  "delete the shim pod".
- **Its blast radius now includes workflow code.** It is the LakeFS `admin`
  user with no lesser role to drop to, so a workflow that leaks it compromises
  LakeFS entirely. Mount it only into steps that genuinely talk to LakeFS.

Consumption pattern (explicit `secretKeyRef`, `optional: false`, HTTP Basic
against `http://lakefs.mlops.svc.cluster.local:80`) is documented in
[`mlops-app-auth.md`](./mlops-app-auth.md)
([ADR-0091](../adr/0091-mlops-programmatic-access-and-bearer-audience.md)).

## Runbook — rotate or recover the LakeFS admin credential

The shim cannot log in without `lakefs_admin_access_key_id` /
`lakefs_admin_secret_access_key` (ASM key `ai/camer/digital/prod/env`).

⚠️ **`lakefs superuser` is not a reset.** `lakefs superuser --user-name X`
**creates** a new admin and prints its access-key/secret **once**; if `X`
already exists it errors `already exists` and prints nothing. Because LakeFS
OSS is single-user, there is no second name to fall back on either.

**Rotation (credential known / a fresh name available):** run `lakefs superuser`
with a new name inside the LakeFS pod, capture the printed pair, write it to the
two ASM properties, then restart `lakefs-proxy` so the env re-binds.

**Recovery (credential lost).** Only safe while LakeFS holds **no repositories**
— this wipes the metadata KV store.

1. Prove LakeFS is empty, from the LakeFS Postgres DB:

   ```sql
   select count(*) from kv where encode(key,'escape') like 'repos/%';
   ```

   Anything other than `0` — **stop**. You would destroy real repositories;
   escalate instead.
2. `TRUNCATE TABLE kv;`
3. Delete the LakeFS pod so it restarts against the empty store.
4. `lakefs superuser --user-name <new-name>` in the fresh pod; capture the
   printed access-key id + secret **immediately** (printed once).
5. Store them as `lakefs_admin_access_key_id` / `lakefs_admin_secret_access_key`
   in `ssegning-aws` (`ai/camer/digital/prod/env`), let ESO resync, then delete
   the `lakefs-proxy` pod — `secretKeyRef` env binds at pod start and never
   refreshes.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| **Infinite redirect loop** between Keycloak and LakeFS | oauth2-proxy is not forwarding the identity header — `--set-xauthrequest` missing/false — so the shim never sees an authenticated request and keeps bouncing | Set `set-xauthrequest: "true"` in the `lakefs-auth` `extraArgs`; re-roll the oauth2-proxy pod |
| **503 with a "SSO handshake did not complete" style message** | The shim's **loop guard** fired: the browser came back carrying `_lakefs_sso=1` but still no `internal_auth_session` cookie. Usually the browser is dropping the cookie (third-party/`Secure` mismatch, aggressive privacy blocking) or LakeFS rejected the login and no `Set-Cookie` was ever relayed | Check the shim logs for the `/api/v1/auth/login` result; if it succeeded, the cookie is being dropped client-side (test in a clean profile, confirm the host is HTTPS-only) |
| **502 at the front door**, shim logs an admin-login failure | The `lakefs-proxy-admin` credential is wrong, empty, or was invalidated (e.g. the KV store was wiped without re-issuing) | Verify the two ASM properties; if lost, follow the recovery runbook above; delete the shim pod afterwards so the env re-binds |
| **`ImagePullBackOff` on `lakefs-proxy`** | `ghcr.io/adorsys-gis/lakefs-proxy` is a **private** package and pull secrets are namespace-scoped — the `converse` copy does not serve `mlops` | Confirm the `lakefs-ghcr` dockerconfigjson exists in `mlops` (from `charts/lakefs-secrets`) and that it is referenced from bjw's `defaultPodOptions.imagePullSecrets` — **not** `global.imagePullSecrets`, which bjw ignores |
| **`CreateContainerConfigError` on `lakefs-proxy`** | `lakefs-proxy-admin` has not synced yet. This is **by design**: the credential env is `optional: false`, so the pod waits instead of starting with an empty key and 502-ing forever | Check the `ExternalSecret`/ESO status; the pod starts on its own once the Secret exists |
| **LakeFS's own access-key login form appears** | Traffic reached LakeFS without passing through the shim — usually a re-enabled chart ingress, or oauth2-proxy's `--upstream` pointing at LakeFS directly | `ingress.enabled: false` on the LakeFS chart; `--upstream` = the `lakefs-proxy` Service |
| **oauth2-proxy `CrashLoopBackOff`, `cookie_secret must be 16, 24, or 32 bytes … is 44 bytes`** | The cookie secret is padded base64 | Regenerate with `openssl rand -hex 16` and update the ASM property |
| **Everything works but commits are attributed to `admin`** | Not a bug — LakeFS OSS is single-user (see the top of this page) | Nothing to fix; use the oauth2-proxy/shim logs for per-person attribution |

Diagnostic order for anything else: **oauth2-proxy logs** (did Keycloak
authenticate?) → **shim logs** (did the login POST succeed, was a `Set-Cookie`
relayed?) → **LakeFS logs** (did it reject the credential?). The Cilium policies
enforce on **container** ports — `lakefs-auth → lakefs-proxy:8080` and
`lakefs-proxy → lakefs:8000` — even though both Services publish `:80`.

## Supply chain

`lakefs-proxy` is the only first-party image in the `mlops` namespace, built out
of [`adorsys-gis/lakefs-proxy`](https://github.com/ADORSYS-GIS/lakefs-proxy).

- ⚠️ **Build it with `cargo-auditable`.** Trivy scans **zero** Rust crates from a
  plain Rust image — it only sees the base OS, so a green scan is meaningless.
  With `cargo-auditable` embedded metadata, Trivy reports a `rustbinary` target
  (110 packages for this image). This applies to *any* Rust image behind a Trivy
  gate.
- ⚠️ **GitHub-hosted Actions runners are billing-blocked org-wide**
  (`The job was not started because recent account payments have failed…`).
  Every adorsys-gis repo works around this with `runs-on: adorsys-gis-runner`
  (self-hosted ARC) — the shim's repo does the same.
