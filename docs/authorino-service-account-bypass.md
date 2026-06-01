# Authorino: bypass OPA / external metadata for service accounts

**Chart:** `charts/kuadrant-policies`
**App:** `security-policies` (in `charts/apps/values.yaml`)
**Authorino API:** `authorino.kuadrant.io/v1beta3`

## What this does

Allows specific Authorino AuthConfig **steps** (metadata, authorization) to be
skipped when the incoming JWT was issued to a service account, while keeping
authentication (JWT verification) mandatory for everyone.

A "service account" here means: a Keycloak client with
`serviceAccountsEnabled: true` whose token's `azp` claim equals the client ID.
Examples in this repo:

- `adorsys-gis-github-ci` — GitHub Actions runner
- `lightbridge-api-key` — Lightbridge service identity

Membership in the allowlist is itself the authorization decision for SAs.
Add a client only if you are happy granting it the same access a `project.id`-
validated human caller would receive.

## How it works

Two pieces in the chart:

1. **Top-level `serviceAccountClients` list** on each AuthConfig — the
   allowlist.
2. **Per-step `_skipForServiceAccounts: true` marker** — the opt-in that says
   "skip this step for SAs". The chart template:
   - Strips the marker before rendering (Authorino never sees it).
   - Appends `when: [ azp neq <client>, … ]` predicates to the step, one per
     allowlisted client. They are AND'd, so the step runs only when `azp`
     differs from EVERY entry (i.e. the caller is not a known SA).
   - If the step already had a user-supplied `when:` block, the SA-exclusion
     predicates are appended to it; the original predicates are preserved.

Result: the step is silently no-op'd for SA tokens; everything else behaves
unchanged.

## Where the wiring lives

### chart values shape (`charts/kuadrant-policies/values.yaml`)

```yaml
authConfigs:
  <name>:
    hosts: [...]
    serviceAccountClients:
      - adorsys-gis-github-ci
      - lightbridge-api-key
    authentication: { ... }      # always runs
    metadata:
      "step-name":
        _skipForServiceAccounts: true
        http: { ... }
    authorization:
      "step-name":
        _skipForServiceAccounts: true
        patternMatching: { ... }
    response: { ... }            # always runs (see "Known limitation" below)
```

### production values (`charts/apps/values.yaml`, `security-policies` app)

The lightbridge-opa metadata call and the dependent `enforce-valid-key`
authorization step are both marked:

```yaml
authConfigs:
  main:
    serviceAccountClients:
      - adorsys-gis-github-ci
      - lightbridge-api-key
    metadata:
      "lightbridge-validation":
        _skipForServiceAccounts: true
        http: { url: https://lightbridge-opa.converse.svc.cluster.local:3000/... }
    authorization:
      "enforce-valid-key":
        _skipForServiceAccounts: true
        patternMatching:
          patterns:
            - selector: "auth.metadata.lightbridge-validation.project.id"
              operator: "neq"
              value: ""
```

## Adding a new service account

1. In Keycloak, create the client with `serviceAccountsEnabled: true` and
   capture the `clientId`.
2. Add the `clientId` to `serviceAccountClients` in
   `charts/apps/values.yaml` (under the relevant `authConfigs.<name>` block).
3. Commit + push; ArgoCD reconciles the AuthConfig with a longer `when:` list.
4. Verify: see "Testing" below.

## Marking a new step skippable

Set `_skipForServiceAccounts: true` on any `metadata` or `authorization` entry.
Nothing else to wire — the chart helper handles predicate generation.

> The marker is supported on `metadata` and `authorization` entries only. It is
> ignored elsewhere.

## Testing

Two curl calls against the gateway prove the behaviour end-to-end.

```bash
# 1. Human token — must trigger lightbridge-validation and enforce-valid-key
HUMAN_TOKEN=$(kc-token --client-id converse-frontend ...)   # see kc-token CLI
curl -sv -H "Authorization: Bearer $HUMAN_TOKEN" https://api.ai-v2.camer.digital/...
# Expect: 200 if the human's API key is valid in lightbridge,
#         403 / "missing project.id" otherwise.

# 2. SA token — must bypass lightbridge-validation entirely
SA_TOKEN=$(kc-token --client-id adorsys-gis-github-ci \
                    --client-secret "$KC_CLIENT_SECRET" \
                    --grant client_credentials)
curl -sv -H "Authorization: Bearer $SA_TOKEN" https://api.ai-v2.camer.digital/...
# Expect: 200, regardless of lightbridge state.
```

Authorino debug logging shows the skipped step as
`skipping evaluation: when condition not met`. To inspect at the chart level:

```bash
# Make sure the rendered AuthConfig has the expected `when:` blocks.
helm template kuadrant-policies charts/kuadrant-policies \
  -f <(yq '.apps[] | select(.name=="security-policies").source.helm.valuesObject' \
       charts/apps/values.yaml) \
  | yq '.spec'
```

## Known limitation: response headers still depend on missing metadata

The `response.success.headers` block in `security-policies/main` injects
`x-project-id`, `x-account-id`, `x-api-key-id`, `x-billing-plan`,
`x-api-key-status`, and dynamicMetadata of the same — all sourced from
`auth.metadata.lightbridge-validation.*`. For SAs the metadata step is skipped,
so these selectors resolve to empty strings.

Downstream services receive headers like `x-project-id: ""`. This is acceptable
when downstream treats empty as "no project / SA caller". If your service
crashes on empty values, either:
- Strip those response entries with `_skipForServiceAccounts: true` too (the
  template does **not** currently honor the marker inside `response.success.*`
  — would need a follow-up refactor), OR
- Update the downstream to treat empty as "no project context".

## Security implications

- **Trust placement:** Adding a client to `serviceAccountClients` says "I trust
  every token issued by this client to bypass project/api-key validation". The
  trust is in Keycloak's identity assertion + the client's secret hygiene.
- **Revocation:** Removing a client from the allowlist immediately re-enables
  full OPA validation for that client's tokens on the next ArgoCD sync.
  Tokens already in flight continue to be honored until they expire (typical
  Keycloak access-token lifetime: 5 minutes for camer-digital realm).
- **Audit:** Authorino logs both branches. Filter for the AuthConfig name +
  `azp=<client-id>` to see exactly which steps ran for which client.

## Why not use the JWT `typ` claim, absence of `email`, or a realm role?

Considered and rejected (see prior session decision):

- **typ != Bearer / custom scope:** any caller can request scopes; low trust.
- **Absence of email claim:** breaks if anyone adds an email mapper to a SA
  client or removes it from a human one. Implicit; easy to misconfigure.
- **Realm role marker:** more flexible but requires every SA client to be
  added to a specific realm role, plus a one-time realm config change. The
  allowlist is explicit, auditable, and adding a new SA is a one-line PR.

## Related

- `charts/kuadrant-policies/templates/_helpers.tpl` — `skipSAWhen` + `authStep`
  helpers.
- `charts/kuadrant-policies/templates/authconfig.yaml` — uses the helpers.
- `docs/keycloak-audience-operations.md` — overall audience / scope policy.
