# ADR-0067: JWT-token-level consumption dashboard (email from the JWT claim only)

**Status:** Accepted
**Date:** 2026-06-27
**Deciders:** @stephane-segning
**Builds on:** [ADR-0046](./0046-per-user-attribution-otlp-envelope-repair.md), [ADR-0011](./0011-oidc-downstream-headers.md), [ADR-0058](./0058-precompute-gateway-usage-metrics-to-mimir.md), [ADR-0064](./0064-keycloak-sessions-and-grants-visibility.md), [ADR-0008](./0008-python-dashboard-generation.md)

## Context

The per-user / user-directory / sessions-grants dashboards answer "who spent
what" at the **person** level (keyed on the Keycloak `sub`, resolved via the
Keycloak datasource, ADR-0063/0064). A distinct question remained: **per
individual JWT (access token) — what did it consume, and when was it last used?**
— with the user's email taken **from the JWT claim only**, not the Keycloak
directory.

Two facts from the existing pipeline shape the answer:

- The JWT id (`oidc_jti`) and the JWT email (`oidc_email`) are written by Envoy
  into the access log. Alloy's `ai_gateway_user_attribution` stage (ADR-0046)
  promotes `email` to a **Loki stream label**, but `oidc_jti` stays a **body
  field** — it is **deliberately NOT a Mimir metric label** (ADR-0064 rejected
  promoting `jti`: every access token is a new id → unbounded cardinality).
- Therefore per-`jti` aggregation **cannot** come from the precomputed Mimir
  metrics (ADR-0058) — only from Loki, where the body field lives.

## Decision

Ship a generated **`jwt-tokens`** dashboard
(`tools/dashboards/envoy_ai_gateway/jwt_tokens.py`,
`…/files/envoy-ai-gateway/jwt-tokens.json`) that is **Loki-backed** and keyed on
`oidc_jti` × the JWT-derived `email` label:

- stats (distinct JWTs / cost / tokens / requests over range),
- **Top JWTs by cost** and **by tokens** (bargauge, legend `<email> · <jti>`),
- **Cost per JWT over time** (the temporal "usages" view),
- **Last usages** — a Loki logs panel of recent requests, newest first.

**Email from the JWT only.** The `email` axis is the Loki label Alloy promotes
from `oidc_email`; the Keycloak datasource is **not** involved. Thin tokens with
no email claim show their `missing:*` / `unstamped:*` sentinel — that is the
honest "from the JWT only" view, not a gap to paper over.

**LogQL contract (the load-bearing detail):** `oidc_jti` must be extracted in the
**same** `| json` stage that the outer `sum by (oidc_jti, email)` groups on —
extracting only the unwrap field collapses `oidc_jti` to `-`. Numeric usage
fields have literal dotted keys (`gen_ai.usage.total_tokens`) → backtick-quoted
bracket form `field=["dotted.key"]`; every `unwrap` needs `| __error__=""`
(values are strings, absent ones `"-"`); cost is micro-USD → `÷1e6`. Queries are
**range** (never instant — the Loki plugin doesn't substitute `$__range` in
instant queries). The default range is **6h** (access-token timescale) and
leaderboards use `topk(20)`.

## Consequences

- **Token-granularity that the person-level boards intentionally don't give.**
  "Which individual token burned the budget, and when was it last active" is now
  answerable directly.
- **Bounded cardinality, verified.** `oidc_jti` is high-cardinality in theory,
  but live it's small (~a handful of distinct `jti`/hour — access tokens are
  reused across many requests), so `sum by (oidc_jti, email)` stays well under
  Loki's 500-series cap at a 6h range. If usage scales, narrow the range or the
  `topk` — do **not** promote `jti` to a Mimir label (ADR-0064 stands).
- **Honest about thin tokens.** Sentinel emails (`missing:github:email`,
  `missing:lightbridge:email`, `unstamped:email`) appear as-is — they mark CI /
  service / unclaimed tokens. Fixing them is the separate "always stamp
  `x-oidc-user-name`/email" work, not this dashboard's job.
- **No new infra / grants.** Pure dashboards-as-code over the existing Loki
  stream; no datasource, secret, or DB-grant change.
