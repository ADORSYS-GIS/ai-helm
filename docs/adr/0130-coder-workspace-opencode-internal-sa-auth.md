# ADR-0130: Authenticate Coder workspace OpenCode to the internal gateway via a per-workspace ServiceAccount

**Status:** Proposed
**Date:** 2026-08-10
**Deciders:** @stephane-segning

## Context

OpenCode runs inside Coder workspaces and must call the Camer Digital AI gateway while attributing spend to the Coder user who started the workspace. The current template (`.coder/templates/opencode-task/`) injects the owner's OIDC access token (`aud=coder`) into the pod and relies on the gateway accepting "any valid realm token" — a known anti-pattern (ADR-0091: a shared realm JWKS is not an authorization boundary), and it places a real user credential in a user-controlled pod. The architect wants everything internal, Authorino for authentication, and per-user attribution tied to the Coder login, with OpenCode holding no real credential (a dummy key is preferred). The owner's `billing_plan` must be available for per-user budget enforcement (ADR-0035); it is a Keycloak user attribute exposed via a protocol mapper (ADR-0021).

## Decision

Adopt a **per-workspace Kubernetes ServiceAccount** as the credential and identity carrier for OpenCode in a Coder workspace, talking to the **internal** AI gateway:

- **OpenCode uses a dummy key** and points at an **openresty sidecar** (`localhost:8080`) that reads the projected SA token **per request** (Lua) and injects it as `Bearer`. Caddy was rejected at implementation: its `{file.read}` placeholder does not resolve in `header_up`, so it cannot inject the rotating (1h) SA token — verified live.
- The SA is named **`coder-<sub>.<plan>`** (both the owner's identity and billing plan in the *name*), set by the template at provisioning from the decoded login JWT.
- **Authorino** validates the SA token via `kubernetesTokenReview`, then derives both values by **pure CEL** from the SA name: take the last `:`-segment (the SA name), split on `.` (the plan delimiter), and strip the fixed `coder-` prefix for the `sub`. No SA-label read, no Kubernetes-API metadata call, and the parse is **robust to any `sub` length** (the `.` never appears in a Keycloak `sub` or a plan).
- **Envoy** enforces per-user budget/burst on `x-account-id`.
- The workspace pod is hardened: OpenCode (dummy key) + a non-root, read-only-FS openresty sidecar; the SA is least-privilege (no RBAC).

## Consequences

**Positive**
- Fully internal — no public-LB hairpin; the workspace talks to `core-gateway-internal.svc`.
- Non-forgeable identity — the `sub`/plan live on the SA (a server-side object the user lacks RBAC to modify), not in a client-supplied header.
- OpenCode holds no real credential — the token lives only in the sidecar.
- Auto token rotation — the kubelet refreshes the projected SA token.
- Per-user attribution + per-user budget enforcement (no misuse of resources) keyed on `x-account-id`.

**Negative**
- **Plan is fixed at provisioning** — changing a user's plan requires rebuilding the workspace (the plan is in the SA name). Acceptable: plans change rarely.
- Per-workspace SA object churn (scales linearly with workspace count).
- Requires the `billing_plan` protocol mapper on the `coder` Keycloak client so the login JWT carries the plan (verified: a password-grant token for `coder` now includes `billing_plan=free`).

**Neutral / follow-ups**
- The openresty sidecar shares the pod's network namespace with the user container; credential secrecy (token read only in the sidecar) is the primary control, with a CiliumNetworkPolicy as defense-in-depth.
- No resource lookups at request time (plan comes from the SA name), so no Authorino RBAC / CA-trust / per-request API call is needed.

## Alternatives considered

- **Caddy sidecar** — rejected at implementation: verified live that `{file.read}` does not resolve as a per-request placeholder in `header_up`, so Caddy cannot inject the rotating SA token (and a single-line `handle` block is invalid Caddy syntax). openresty reads the token file per request.
- **Plan in the SA label (read via a Kubernetes-API metadata step)** — rejected: verified live that this needs Authorino to trust the cluster CA + a K8s token with SA-read RBAC + a per-request API call, and the fetched-path was unreliable (`kind: Status`). Putting the plan in the SA name removes all of it.
- **Plan encoded in the SA name** — chosen (this ADR): both `sub` and plan derive from the name via pure CEL, delimited by `.` (robust to any `sub` length). Trade-off: plan changes need a workspace rebuild.
- **Rust proxy (separate pod)** — rejected: adds a second pod and a custom service to build/maintain, plus a missing first-party image CI pipeline.
- **User's own Keycloak token in the pod** — rejected: a real credential in a user-controlled pod, and token refresh complexity for long-lived workspaces.
- **Static apiKey (k8s Secret)** — rejected: manual secret management and rotation; per-workspace Secret sprawl.
- **mTLS client cert** — rejected: certificate/Envoy client-auth setup outweighs the benefit here.
- **Cached plan resolver (lightbridge-repo-auth)** — rejected: `lightbridge-repo-auth` holds GitHub org IDs, not Keycloak subs; a `sub → plan` resolver would need a new Keycloak-querying component.

## Related

- Docs: `docs/integrations/coder-workspace-opencode-auth.md` (design), `docs/integrations/coder-workspace-opencode-auth-flow.md` (flows), `docs/images/coder-workspace-opencode-auth.drawio` (diagram)
- Files: `.coder/templates/opencode-task/main.tf`, internal AuthConfig (`ai-helm-values` `security-policies.yaml`), `environments/<env>/deps/<app>/` CiliumNetworkPolicy
- Builds on: ADR-0021 (internal plane + forwarded-user attribution), ADR-0037 (SA-token internal-plane pattern), ADR-0035 (per-person budgets), ADR-0091 (audience pinning)
- Supersedes: (informally) the injected-owner-token approach in `.coder/templates/opencode-task/`
