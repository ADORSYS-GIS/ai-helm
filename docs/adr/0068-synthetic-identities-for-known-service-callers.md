# ADR-0068: Structured synthetic identities for known non-human callers

**Status:** Accepted
**Date:** 2026-06-27
**Deciders:** @stephane-segning

## Context

ADR-0052 made every absent identity claim resolve to a loud, source-qualified
sentinel (`missing:<source>:<claim>` / `unstamped:<field>`) instead of an empty
value Loki would silently drop. That fixed *invisible* gaps — but it lumped two
very different things under one `missing:*` shape:

1. A genuine **attribution gap** — a Keycloak human whose token lacked `email`
   (a real token/client problem to chase).
2. A **known non-human caller** that legitimately carries no human email but
   whose *identity is perfectly well known from other fields*: GitHub CI (the
   `repository` claim), Lightbridge Code Intelligence (the forwarded
   `x-code-intelligence-*` headers), and LibreChat-forwarded end users (the
   `x-librechat-user` Keycloak sub).

For case 2 the data to name the caller was *already on the request* — we were
throwing it away into `missing:github:email` / `missing:lightbridge:email` /
`missing:librechat:jti` and then squinting at `azp` to tell who it was. On the
JWT-token board (ADR-0067) this surfaced as e.g.
`jti=missing:librechat:jti` for a request whose LibreChat user id was right there.

## Decision

**For *known* non-human callers, synthesize a structured identity from the
fields the request already carries, at the Authorino (AuthConfig CEL) layer —
not in Grafana.** Two structured shapes:

- **Email = `<resource>@<originating-service>`** — a readable, groupable pseudo-
  address whose local part is the resource the call acts for and whose domain is
  the service that issued it:
  - GitHub CI → `<owner/repo>@gh-runners` (e.g. `ADORSYS-GIS/ai-helm@gh-runners`)
    from `auth.identity.repository`.
  - LCI → `<owner/repo>@lightbridge-code-intelligence` (e.g.
    `vymalo/flutter-tools@lightbridge-code-intelligence`) from
    `x-code-intelligence-repo`.
  - LibreChat → the **real** forwarded user email, unchanged.
- **JTI = `<kind>:<id>`** — the per-call trace handle:
  - GitHub CI → `runid:<run_id>` (the workflow run; `has()`-guarded, falls back
    to the raw GitHub `jti` then `missing:github:jti`).
  - LCI → `runid:<task-id>` from `x-code-intelligence-task-id`.
  - LibreChat → `librechat:<user-id>` from `x-librechat-user`.

The human/service split stays an **Authorino-set** signal — the existing
`billing_plan` (`internal` for services) and `azp` Loki labels — **not** a
Grafana email-regex. So these synthetic service emails are *intentionally* not
matched by the per-user board's `(missing|unstamped):.*` exclusion: services
become first-class, named, attributable identities that show up on the cost
boards like anyone else, and are filtered in/out by `billing_plan`/`azp` when a
panel wants humans-only. Genuine gaps (a Keycloak human with no email, a raw
cron/SA caller) keep their honest `missing:keycloak:*` / `missing:service:*`
sentinel.

Scope is **email + jti only** (display/attribution). The rate-limit descriptors
`x-account-id`/`x-org-id`/`x-billing-plan` are untouched — budget bucketing is a
separate decision (ADR-0052 follow-up, still deferred).

## Consequences

**Positive**
- CI runs, LCI reviews, and LibreChat sessions are named and groupable on the
  cost/JWT boards instead of collapsing into `missing:*` buckets — "which repo's
  CI burned that spend" is answerable at a glance.
- The human/service boundary is enforced once, at the root (Authorino labels),
  so dashboards don't carry brittle email-string heuristics.
- Negligible cost: compiled CEL, no added I/O (same as ADR-0052).

**Negative**
- The per-user *human* panels now include synthetic service emails unless a
  panel explicitly filters on `billing_plan`/`azp`. That's the intended trade
  (services are first-class), but any human-only panel must filter on the label,
  not assume the email exclusion drops them.
- Synthetic emails contain `/` and `@` — valid Loki label values (the old
  colon-bearing sentinels already proved arbitrary chars are fine), but they are
  *not* real addresses; nothing downstream should treat them as deliverable.

**Neutral / follow-ups**
- ⚠️ `run_id` is a standard GitHub Actions OIDC claim but is `has()`-guarded and
  must be **confirmed on a live CI token** — until then a gh-runner with no
  `run_id` falls back to the raw GitHub `jti`/sentinel (safe, just less pretty).
- Budget bucketing on the synthetic identity (per-repo / per-service budgets)
  remains future work — would touch `x-account-id`/`x-org-id` and rate limiting.

## Alternatives considered

- **Keep `missing:*` and split humans vs services with a Grafana email-regex** —
  rejected: pushes the identity logic into every dashboard, brittle, and exactly
  what the maintainer called out ("tackle it at the Authorino layer, not Grafana").
- **Synthesize in Alloy (River) instead of Authorino** — rejected: Alloy only
  sees the *stamped header values*, not the raw JWT claims / forwarded headers
  (`repository`, `run_id`, `x-code-intelligence-*`), so it can't build these.
  Authorino is the only layer with the source fields.
- **Flow the synthetic identity into the budget buckets too** — deferred (not
  rejected): materially changes rate-limit accounting; out of scope here.

## Related

- Extends [0052](./0052-source-qualified-missing-claim-sentinels.md) (sentinels);
  builds on [0011](./0011-oidc-downstream-headers.md) (x-oidc-* contract),
  [0046](./0046-per-user-attribution-otlp-envelope-repair.md) (Alloy label
  promotion), [0047](./0047-github-oidc-repo-binding-for-ci.md) (GitHub plane),
  [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md) (dual plane),
  [0067](./0067-jwt-token-consumption-dashboard.md) (the JWT board this improves).
- Files: `ai-helm-values` `environments/prod/values/security-policies.yaml`
  (both AuthConfig planes — the AuthConfig moved out of `charts/apps/values.yaml`
  per ADR-0056). No dashboard change required; the boards display the new values.
- Docs: [per-user-observability.md](../per-user-observability.md),
  [jwt-token-observability.md](../jwt-token-observability.md) (the *how*).
