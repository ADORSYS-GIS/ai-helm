# ADR-0003: Skip OPA / external metadata for service-account tokens via `azp` allowlist

**Status:** Accepted
**Date:** 2026-05-24
**Deciders:** repo maintainers via `claude/magical-bohr-390242`

## Context

The Authorino AuthConfig fronting the AI Gateway runs three steps after JWT
verification: an external metadata call to `lightbridge-opa` (validates an
API key against an internal directory and returns project/account/billing
info), a `patternMatching` authorization step that requires the returned
`project.id` to be non-empty, and a `response.success` block that injects
the returned fields as downstream headers.

This works for human callers — they own API keys in the lightbridge directory.
It does not work for service-account tokens (GitHub runner, Lightbridge's own
service identity, etc.): they have no API key, the metadata call returns
empty, the authorization step rejects them, and the gateway 403s.

We need SAs to pass through. They are already authenticated by Keycloak; the
question is how to express "these tokens skip the API-key path".

## Decision

Add a chart-level `serviceAccountClients` allowlist on the AuthConfig values
(`adorsys-gis-github-ci`, `lightbridge-api-key` to start). Mark individual
steps with `_skipForServiceAccounts: true`. The chart template strips the
marker and appends `when: [ azp neq <client>, … ]` predicates to the step,
preserving any user-supplied `when:` block.

Authentication (JWT verification) remains mandatory for everyone. Only the
lightbridge-opa metadata + the dependent authorization step are skipped for
SAs. Allowlist membership is the authorization decision for SAs — adding a
client to the list is the gate.

## Consequences

**Positive**
- Explicit, auditable list of SA clients in one place.
- Adding a new SA is a one-line PR — no template changes, no realm changes.
- Authorino debug logs show exactly which steps ran for which client.
- Pattern is reusable for any future skip-for-SAs need (e.g. a billing-quota
  step that doesn't apply to internal service accounts).

**Negative**
- Trust is placed in Keycloak's identity assertion plus the client's secret
  hygiene. Standard OAuth assumption, but worth naming.
- `response.success.headers` selectors against `auth.metadata.lightbridge-validation.*`
  resolve to empty strings for SAs. Downstream services receive
  `x-project-id: ""` etc. — acceptable today (downstream treats empty as
  "no project context"), but is a known limitation documented in the
  ops doc.

**Neutral / follow-ups**
- If downstream changes to reject empty headers, extend the chart template
  to honor `_skipForServiceAccounts` inside `response.success.headers` /
  `dynamicMetadata` entries too.
- Token revocation on allowlist change: removing a client takes effect on
  the next ArgoCD sync, but tokens already issued continue to be honored
  until they expire (≤5 minutes on this realm). Document, don't fight.

## Alternatives considered

- **`typ` claim != Bearer / custom scope** — any caller can request scopes;
  trust placement is weak. Rejected.
- **Absence of `email` claim** — relies on Keycloak's default SA token shape.
  Breaks silently if anyone adds an email mapper to a SA client (or removes
  it from a human one). Implicit; easy to misconfigure. Rejected.
- **Realm-role marker (`service-account` role)** — more flexible but
  requires a one-time realm config change and adding the role to every SA
  client. More moving parts than the allowlist. The allowlist is explicit;
  one place to read; one place to change. Rejected as the default; could
  be added on top if a need arises.

## Related

- Commit: `84ab1ff`
- Doc: `docs/authorino-service-account-bypass.md` (the how — adding new SAs,
  testing recipe, troubleshooting matrix)
- Charts touched: `charts/kuadrant-policies/templates/{_helpers,authconfig}.yaml`,
  `charts/apps/values.yaml` (security-policies block)
