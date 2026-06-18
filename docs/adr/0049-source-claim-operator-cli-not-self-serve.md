# ADR-0049: Claim Sources via an operator CLI, not a self-serve UI (for now)

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** @stephane-segning

## Context

ADR-0047 binds a GitHub org to a billing account: the install webhook creates a
*Source* (`repository_owner_id → installation`), and a **claim** step links it to
an `account_id` (stamped `x-account-id`). Until claimed, `/v1/resolve` denies.

The original sketch had a Vymalo dashboard claim the Source on the post-install
redirect. But we are **not opening this to arbitrary customers** — the platform
serves a small, known set of first-party orgs (≤ ~5). Building a self-serve
onboarding UI (login + GitHub OAuth + ownership proof) is disproportionate to
that, and a public claim surface is attack surface we don't need yet.

## Decision

1. **The claim API stays "dumb but guarded":** `POST /v1/admin/claim` +
   `GET /v1/admin/sources` on `lightbridge-repo-auth` are **ClusterIP-only** and
   gated by the `X-Internal-Token`. The service just writes the binding; it holds
   **no** identity/ownership policy.
2. **Claim via an operator CLI**, not a UI: `repo-auth-ctl` (in the service repo)
   talks to that admin API. When one of our orgs installs the App, an operator
   runs `repo-auth-ctl sources` / `claim --owner-id … --account-id … --plan …`.
   There is **no public self-serve claim**.
3. **Document the self-serve design for if/when we open up** (not built): a
   dashboard would do "Login with GitHub" (OAuth) and verify the claimer
   **administers the installation** via `GET /user/installations` (GitHub only
   lists installations the user manages) — plus a signed `state` on
   dashboard-initiated installs — **before** calling the same claim endpoint.
   `installation_id` from the redirect is **not** proof on its own (a ghost can
   replay someone else's). The endpoint stays dumb; the dashboard owns identity +
   ownership proof.

## Consequences

**Positive**
- Smallest surface: no public claim endpoint, no OAuth/session code in the
  service, nothing for a "ghost" to hit. Security is by restriction.
- Right-sized for ≤5 orgs; the CLI reuses the typed `ClaimRequest` and is a thin
  HTTP client (no deploy — operator tool).
- The anti-ghost design is captured, so a future UI can't be built weaker.

**Negative**
- Manual, operator-in-the-loop per org install (acceptable at this scale; doesn't
  scale to many customers — that's the trigger to build §3).
- The CLI needs cluster access + the internal token (port-forward); it's an
  operator tool, not self-service.

**Neutral / follow-ups**
- Re-claim / transfer / fix-ups use the same CLI (break-glass).
- Build the self-serve flow (§3) only when onboarding external customers; until
  then it stays documented-not-implemented.

## Alternatives considered

- **Self-serve claim UI now** — rejected: disproportionate for ≤5 first-party
  orgs and adds a public claim surface (+ OAuth/UI) we don't need yet.
- **Raw DB writes to claim** — rejected: no validation, no audit, error-prone,
  and (rightly) gated as a production-DB write.
- **Push GitHub-OAuth ownership proof into `lightbridge-repo-auth`** — rejected:
  bloats a focused store service with session/OAuth concerns; that policy belongs
  in the (future) dashboard, which calls the dumb claim endpoint.

## Related

- Builds on: [ADR-0047](./0047-github-oidc-repo-binding-for-ci.md)
- Service + CLI: [lightbridge-repo-auth](https://github.com/ADORSYS-GIS/lightbridge-repo-auth) (`repo-auth-ctl`, `/v1/admin/*`); App scopes: its `docs/github-app-permissions.md`
