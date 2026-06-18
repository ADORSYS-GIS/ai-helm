# ADR-0052: Self-diagnosing identity attribution — source-qualified sentinels for absent claims

**Status:** Accepted
**Date:** 2026-06-18
**Deciders:** @stephane-segning

## Context

The per-user Grafana board (ADR-0046, #357) showed junk identity rows — `-`,
`<nil>`, and an unlabeled "Value" bucket — that fragmented real people and
hid real cost. A live trace through the whole pipeline (Authorino → Envoy
access log → Alloy → Loki → Grafana) found those three artifacts are not three
services but **three different encodings of "identity absent," produced at
different layers**, and that the root cause was upstream of all of them:

- **Token shape (root).** Self-service API keys (`azp=lightbridge-api-key`) are
  minted by a Keycloak **token-exchange** (RFC 8693) that produces a **lightweight
  access token** (Keycloak's "Always use lightweight access token") carrying no
  `profile`/`email` scope — so `name`/`email`/`preferred_username` (and sometimes
  `sub`, when impersonation isn't wired) never reach the JWT. The *same human* via
  `opencode-cli` (a normal auth-code flow requesting `openid profile email`) was
  fully attributed; via the API key they were nameless. (The fix for the token
  itself is Keycloak-side — assign the scopes / disable lightweight on that client
  / wire impersonation — and is out of this repo.)
- **Authorino.** Most `x-oidc-*` response headers used a bare `plain.selector`.
  A selector against a missing claim stamps the opaque literal `<nil>`. ADR-0047
  had already `has()`-guarded only `x-oidc-email`/`x-oidc-name`.
- **Envoy + Alloy.** A header Authorino never stamps renders as `-` in the access
  log; Alloy's `^-$` stage **blanked it to `""`**, and **Loki drops empty-valued
  labels** — so the failure became *invisible* (the stream simply had no such
  label), which is exactly why the gap went unnoticed since rollout.
- **Internal plane.** Its AuthConfig never set `x-oidc-name` at all, so every
  in-cluster caller (LibreChat users, cron, services) was nameless by construction.

The recurring lesson: **an empty value is the worst outcome — it hides the
failure.** A request that wasn't attributed should say so, loudly and specifically.

## Decision

**Never resolve an absent identity value to empty. Resolve it to a descriptive,
source-qualified sentinel that names both *what* is missing and *where* it was
lost.** Two namespaces, one per failure layer:

- **`missing:<source>:<claim>`** — set by **Authorino** when the token reached it
  but lacked the claim. `<source>` is determined per request from the identity:
  - external plane, told apart by the GitHub-only `repository` claim:
    `missing:github:<claim>` (often *expected* — GitHub OIDC tokens carry no
    `email`/`preferred_username`/`scope`) vs `missing:keycloak:<claim>` (a real
    Keycloak token/client gap).
  - internal plane: `missing:librechat:<claim>` (a forwarded LibreChat user the
    app didn't forward that field for) vs `missing:service:<claim>` (a non-human
    cron/SA caller, for which the field is legitimately absent).
- **`unstamped:<field>`** — set by **Alloy** when *no header arrived at all*
  (`-`/`<nil>`): the request matched no AuthConfig response, or a plane that omits
  that field. Distinct from `missing:*` so a glance tells you the failure layer.

Concretely:

1. `has()`-guard **every scalar `x-oidc-*` header** in both planes (extends
   ADR-0047 beyond email/name to `sub`, `preferred_username`, `azp`, `scope`,
   `jti`), each terminating in the qualified sentinel. `azp` keeps its meaningful
   `github-actions` fallback; `name` keeps the GitHub repo-slug fallback.
2. The **internal plane gains `x-oidc-name`** (it had none): forwarded
   `X-LibreChat-Name` → else `missing:librechat:name` for a forwarded user → else
   the caller's **own** identity (SA username / apiKey Secret name) so services are
   *named* in the Top-15 instead of collapsing into one bucket. LibreChat now
   forwards `X-LibreChat-Name` (`charts/librechat-app`) so its users resolve by
   name.
3. **Alloy** maps `^(-|<nil>)$` → `unstamped:<field>` (was: blank to `""`).
4. The **dashboard** excludes `(missing|unstamped):.*` from the per-user *human*
   panels (`_SELECTOR`); that traffic stays visible in the Overall section and as
   a named `missing:*`/`unstamped:*` row in the Top-15.

## Consequences

**Positive**
- Every attribution failure is now self-identifying *and* layer-attributed at a
  glance, in raw LogQL and on the board — no cross-referencing, no silent gaps.
- Real users stop fragmenting into anonymous buckets; internal services appear by
  name.
- Negligible cost: the sentinels are compiled CEL (once, at reconcile) with no
  added I/O, crypto, or JWKS/HTTP calls — tens of µs/request against a multi-second
  LLM call. The issuer discriminator is a single `has(auth.identity.repository)`.

**Negative**
- Adds a small, **bounded** set of constant sentinel label values
  (`missing:{github,keycloak,librechat,service}:<claim>`, `unstamped:<field>`) —
  trivial Loki cardinality, but they ARE now labels (empty used to be dropped).
- Defense-in-depth, not the cure: the real token-shape fix for lightweight access
  tokens lives in **Keycloak** (out of repo). Existing long-lived API keys keep
  their claim-poor shape until rotation.

**Neutral / follow-ups**
- The **rate-limit descriptors** `x-account-id`/`x-org-id`/`x-billing-plan` are
  **deliberately NOT yet sentinel-guarded** — they key budget enforcement
  (ADR-0021/0035), so a `missing:*` account would create a shared bucket. Separate
  decision, deferred.
- `x-oidc-roles-realm`/`x-oidc-resource-access` stay plain selectors — they're
  arrays/maps CEL can't cleanly JSON-encode, body-only, never labels.
- After deploy, capture improves as API keys rotate; verify in Loki that
  `lightbridge-api-key` traffic lands named.

## Alternatives considered

- **Blank/empty fallback (`""`)** — rejected: Loki drops empty labels, so the
  failure is invisible. This is the bug we were fixing.
- **Leave bare `selector:` (yields `<nil>`)** — rejected: opaque, and one literal
  for every distinct failure — you can't tell *which* claim or *which* layer.
- **A single unqualified `missing:<claim>`** — rejected: can't distinguish an
  expected GitHub gap from a real Keycloak gap, or a LibreChat-forwarding gap from
  a token gap, without cross-referencing `azp`.
- **Fix only in Keycloak (token scopes/impersonation)** — necessary but not
  sufficient: doesn't cover the `unstamped` (no-header) cases or GitHub's
  legitimately-absent claims, doesn't help in-flight old keys, and leaves the
  pipeline non-diagnosing for the next regression. We do both.
- **Resolve identity via `/userinfo` or the ID token instead of access-token
  claims** — the spec-"correct" home for profile data, but adds a per-request hop
  or a second token at the gateway; rejected on the latency budget. We carry the
  claims in the access token and make absence loud instead.

## Related

- Builds on [0011](./0011-oidc-downstream-headers.md) (x-oidc-* contract),
  [0047](./0047-github-oidc-repo-binding-for-ci.md) (has()-guard origin),
  [0046](./0046-per-user-attribution-otlp-envelope-repair.md) (Alloy promotion),
  [0021](./0021-burst-budget-billing-and-dual-plane-authconfigs.md) (dual plane).
- Charts/files: `charts/apps/values.yaml` (both AuthConfig planes),
  `charts/observability/values.yaml` (Alloy `unstamped:*`),
  `charts/librechat-app/values.yaml` (`X-LibreChat-Name` forwarding),
  `tools/dashboards/src/dashboards/envoy_ai_gateway/per_user.py` (sentinel-aware
  `_SELECTOR`).
- Docs: [per-user-observability.md](../per-user-observability.md) (the *how*).
