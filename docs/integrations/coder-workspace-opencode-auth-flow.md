# Coder Workspace → OpenCode → Internal Gateway — Request Flows & Components

**Status:** Design Proposal (Draft)
**Author:** @benie-joy-possi
**Date:** 2026-08-06

Companion to [`coder-workspace-opencode-auth.md`](./coder-workspace-opencode-auth.md)
and the diagram file
[`docs/images/coder-workspace-opencode-auth.drawio`](../images/coder-workspace-opencode-auth.drawio).
This file gives the **step-by-step request flow** and the **component
explanation** for each option and for the LibreChat pattern we are copying —
written out, not on the diagram.

> **✅ Final decided flow (as built — [ADR-0131](../adr/0131-coder-workspace-opencode-internal-sa-auth.md)).**
> Options A/B below are **superseded** by this converged flow, validated live
> against a real Authorino:
>
> 1. **Login** — user signs into Coder via Keycloak SSO; Coder stores the token.
> 2. **Provision** — Terraform decodes `sub` + `billing_plan` from the login JWT
>    and creates the per-workspace ServiceAccount **`coder-<sub>.<plan>.<workspaceId>`**
>    (workspace UUID suffix = unique per workspace, so same-owner concurrent
>    workspaces — like task-provisioned ones — don't collide on one SA name)
>    plus the workspace pod (OpenCode + an **openresty sidecar**). The SA token
>    (audience `core-gateway-internal`) is projected **only into the sidecar**.
> 3. **Prompt** — OpenCode sends a dummy key to `localhost:8080`.
> 4. **openresty** reads the SA token file **per request** (`io.open(...)`),
>    strips any client identity headers, injects `Bearer <token>`, and forwards
>    to `core-gateway-internal.svc` (trusting the internal CA).
> 5. **Authorino** validates the token (`kubernetesTokenReview`) and derives
>    **both** `sub` and `plan` (after the `.` delimiter) from the SA name
>    by pure CEL — the workspace-UUID third segment is identity-neutral —
>    no SA-label read / no metadata call. Stamps
>    `x-account-id`/`x-billing-plan`.
> 6. **Envoy** enforces the per-user budget on `x-account-id`; response streams
>    back; `user_id = sub` lands on the per-user dashboards.

---

## Option A — per-workspace SA token + Rust proxy

### Components

| Component | What it is | Role |
|---|---|---|
| **Keycloak** | IdP, realm `camer-digital` | Issues the OIDC token (`aud=coder`) when the user logs into Coder. Source of the user's `sub`. |
| **Coder control plane** | Dashboard + Coder DB (`user_links`) + Terraform provisioner | Dashboard does the OIDC login; DB stores the owner's token; Terraform reads the owner's `sub` and provisions the workspace + proxy. |
| **Workspace pod** | User's interactive container running OpenCode | Runs OpenCode. Points at the proxy (`localhost:8080`) with a **dummy key**. Never holds a real credential. |
| **Per-workspace Rust proxy pod** | First-party Rust/axum reverse proxy (like `lakefs-proxy`) | Holds the **projected SA token** (audience `core-gateway-internal`) and the **owner's `sub`** (bound at creation). Strips the dummy key, injects `Bearer <SA token>` + `X-Coder-User: <owner sub>`, forwards to the internal gateway. |
| **Authorino internal AuthConfig** | ext_authz on the internal listener | Validates the SA token via `kubernetesTokenReview`; CEL prefers `X-Coder-User` → `x-account-id` = the user's sub. |
| **Envoy AI Gateway (internal plane)** | `core-gateway-internal.svc` | Routes to the model backends; enforces burst + monthly budget keyed on `x-account-id`. |
| **Per-user dashboards** | Grafana over Mimir/Loki | Show cost/tokens/requests per `user_id` (= sub). |

### Request flow (a prompt from OpenCode)

1. **Login** — user signs into Coder via Keycloak SSO; Coder stores the owner's OIDC token in its DB.
2. **Provision** — user starts a workspace; Terraform reads the owner's `sub`, creates a per-workspace ServiceAccount and a Rust proxy pod, and passes the owner's `sub` to the proxy.
3. **OpenCode → proxy** — OpenCode sends `POST /v1/chat/completions` to `http://localhost:8080/v1` with `Authorization: Bearer local-proxy` (dummy).
4. **Proxy injects** — the proxy strips the dummy key and sets `Authorization: Bearer <projected SA token>` + `X-Coder-User: <owner sub>`, then forwards to `https://core-gateway-internal.envoy-gateway-system.svc/v1` (internal CA trusted).
5. **Authorino authenticates** — validates the SA token via `kubernetesTokenReview` (the cluster is the issuer; audience `core-gateway-internal`).
6. **Authorino attributes** — CEL prefers `X-Coder-User` → `x-account-id` = the owner's sub; stamps `x-billing-plan` and the `x-oidc-*` identity headers.
7. **Gateway enforces + routes** — the per-model `BackendTrafficPolicy` enforces the user's burst + monthly budget on `x-account-id`; Envoy routes to the model backend.
8. **Observability** — Envoy access log carries `user_id` (= sub); Alloy promotes it to a Loki label; the per-user dashboards show the spend.

**Key property:** OpenCode only ever sees a dummy key. The real credential (SA token) and the user identity live in the proxy, which is a **separate pod** so the user container cannot reach the gateway and forge the header.

---

## Option B — static apiKey + Caddy proxy

### Components

| Component | What it is | Role |
|---|---|---|
| **Keycloak** | IdP | Same as Option A — source of the user's `sub`. |
| **Coder control plane** | Dashboard + DB + Terraform | Same as Option A — provisions the workspace + proxy, passes the owner's `sub`. |
| **Workspace pod** | OpenCode container | Same as Option A — points at `localhost:8080` with a dummy key. |
| **Per-workspace Caddy proxy pod** | Stock Caddy reverse proxy (no custom code) | Injects a **static apiKey** as `Bearer` + `X-Coder-User: <owner sub>` from env vars set at pod creation. |
| **Authorino internal AuthConfig** | ext_authz | Validates the **static apiKey**; CEL prefers `X-Coder-User` → `x-account-id` = the user's sub. |
| **Envoy AI Gateway (internal plane)** | `core-gateway-internal.svc` | Same as Option A — routes + enforces budget on `x-account-id`. |
| **Per-user dashboards** | Grafana | Same as Option A — per `user_id` (= sub). |

### Request flow (a prompt from OpenCode)

1. **Login** — user signs into Coder via Keycloak SSO.
2. **Provision** — Terraform creates a Caddy proxy pod and sets `GATEWAY_API_KEY` + `CODER_USER_SUB` as env vars.
3. **OpenCode → proxy** — OpenCode sends the request to `http://localhost:8080/v1` with a dummy key.
4. **Caddy injects** — Caddy sets `Authorization: Bearer <static apiKey>` + `X-Coder-User: <owner sub>` and forwards to the internal gateway.
5. **Authorino authenticates** — validates the static apiKey (matches a labeled Secret).
6. **Authorino attributes** — CEL prefers `X-Coder-User` → `x-account-id` = the owner's sub.
7. **Gateway enforces + routes** — budget/burst on `x-account-id`; route to the model backend.
8. **Observability** — `user_id` (= sub) → Loki label → per-user dashboards.

**Key property:** zero custom code (stock Caddy). The cost is a **static apiKey** that must be rotated (restart the proxy when it changes).

---

## LibreChat — the inspiration (ADR-0021 forwarded-user pattern)

### Components

| Component | What it is | Role |
|---|---|---|
| **End user (browser)** | Human using the LibreChat UI | Logs in via Keycloak SSO. |
| **LibreChat** | Long-running first-party service | Authenticates **as itself** with a static apiKey; forwards the end-user's Keycloak `sub` in `X-LibreChat-User`. |
| **Authorino internal AuthConfig** | ext_authz | Validates the apiKey; CEL **prefers** `X-LibreChat-User` → `x-account-id` = the end-user's sub. |
| **Envoy AI Gateway (internal plane)** | `core-gateway-internal.svc` | Routes + enforces per-user budget on `x-account-id`. |
| **Per-user dashboards** | Grafana | Per `user_id` (= sub). |

### Request flow (a chat message)

1. **Login** — the end user logs into LibreChat via Keycloak SSO.
2. **LibreChat authenticates as itself** — LibreChat calls the internal gateway with `Authorization: Bearer <apiKey>` (its own static key).
3. **LibreChat forwards the user** — it adds `X-LibreChat-User: <end-user sub>` (and role/email) to the request.
4. **Authorino authenticates** — validates the apiKey (LibreChat is a known first-party service).
5. **Authorino attributes** — CEL **prefers** `X-LibreChat-User` → `x-account-id` = the end-user's sub (not "LibreChat").
6. **Gateway enforces + routes** — per-user budget/burst on `x-account-id`; route to the model backend.
7. **Observability** — `user_id` (= sub) → Loki label → per-user dashboards.

### Why it is safe for LibreChat but not directly for a workspace

LibreChat is a **trusted server** — a user cannot forge `X-LibreChat-User` from inside it, because the header is set by LibreChat's own code, not by the user. A **workspace pod is user-controlled** (interactive shell), so if the pod forwarded the header directly, the user could forge it to claim someone else's `sub` and burn their budget. That is why Options A/B **isolate the credential and the identity in a separate per-workspace proxy pod** — the user container cannot reach the gateway, so it cannot forge the header.

---

## The one difference that matters (A vs B)

| | Option A | Option B |
|---|---|---|
| Proxy | custom Rust (first-party) | stock Caddy (no code) |
| Credential | projected SA token (short-lived, auto-rotating) | static apiKey (must be rotated) |
| Authorino auth | `kubernetesTokenReview` | apiKey Secret match |
| Secret surface | none (cluster-issued) | one static apiKey |
| OpenCode config | dummy key → localhost | dummy key → localhost |

Both converge on the same tail: Authorino's CEL prefers `X-Coder-User` →
`x-account-id = owner sub` → per-user budget + per-user dashboards keyed by
`user_id`.

---

## Related

- [`coder-workspace-opencode-auth.md`](./coder-workspace-opencode-auth.md) — the design proposal (context, options, trade-offs, open questions)
- [`docs/images/coder-workspace-opencode-auth.drawio`](../images/coder-workspace-opencode-auth.drawio) — the three-page diagram
- [`ADR-0021`](../adr/0021-burst-budget-billing-and-dual-plane-authconfigs.md) — internal plane + forwarded-user attribution
- [`ADR-0037`](../adr/0037-opencode-agent-internal-sa-token.md) — the SA-token internal-plane pattern
- [`ADR-0035`](../adr/0035-per-person-monthly-budget-and-free-50.md) — per-person budgets keyed on `x-account-id`
- [`patterns/per-user-observability.md`](../patterns/per-user-observability.md) — how `user_id` becomes a Loki label
