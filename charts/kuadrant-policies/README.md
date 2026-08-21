# `kuadrant-policies`

Renders the [Kuadrant](https://kuadrant.io)/[Authorino](https://github.com/Kuadrant/authorino)
resources that gate the AI gateway: `AuthConfig`s (JWT verification +
authorization + response-header stamping), the `Authorino` operator instance(s),
the `SecurityPolicy` that attaches Authorino's ext_authz filter to the Gateway,
and an optional `ExternalSecret` for the repo-auth internal token.

**App:** `security-policies` in [`charts/apps/values.yaml`](../apps/values.yaml)
(workload values now live in the private `ai-helm-values` repo per
[ADR-0056](../../docs/adr/0056-workload-values-in-ai-helm-values.md) — see
"Where the real config lives" below).

**ADRs:** [`0003`](../../docs/adr/0003-skip-opa-for-service-accounts.md) (SA
skip, superseded) · [`0011`](../../docs/adr/0011-oidc-downstream-headers.md)
(`x-oidc-*` contract) · [`0021`](../../docs/adr/0021-burst-budget-billing-and-dual-plane-authconfigs.md)
(dual-plane AuthConfigs, descriptors) · [`0038`](../../docs/adr/0038-mcp-oauth-protected-resource-metadata.md)
(`/mcp/*` carve-out) · [`0047`](../../docs/adr/0047-github-oidc-repo-binding-for-ci.md)
(GitHub OIDC → repo-auth). Read [`docs/architecture/05-auth-identity.md`](../../docs/architecture/05-auth-identity.md)
first — it's the up-to-date narrative this README's mechanics support.

## What it renders

| Template | CRD | Gated by |
|---|---|---|
| [`templates/authconfig.yaml`](templates/authconfig.yaml) | `authorino.kuadrant.io/v1beta3` **`AuthConfig`** (one per entry) | `.Values.authConfigs` |
| [`templates/authorino.yaml`](templates/authorino.yaml) | `operator.authorino.kuadrant.io/v1beta1` **`Authorino`** (one per entry) | `.Values.instances` |
| [`templates/securitypolicy.yaml`](templates/securitypolicy.yaml) | `gateway.envoyproxy.io/v1alpha1` **`SecurityPolicy`** (one per entry) | `.Values.securityPolicies` |
| [`templates/repo-auth-secret.yaml`](templates/repo-auth-secret.yaml) | `external-secrets.io/v1` **`ExternalSecret`** | `.Values.repoAuthInternalSecret.enabled` |

Every resource name is `{{ include "common.names.name" . }}-<entry-key>` (e.g.
`kuadrant-policies-main`), so `authConfigs`/`instances`/`securityPolicies` are
maps keyed by a short logical name, not a list.

Default [`values.yaml`](values.yaml) is intentionally empty (`authConfigs: {}`,
`instances: {}`) — this chart renders **nothing** with its own defaults and
`helm lint`/`helm template` pass vacuously. All real config is supplied by the
consuming app (see below). Don't add fixture defaults here; they'd have to be
kept in sync with the real AuthConfig by hand and would drift.

## Where the real config lives

Per [ADR-0056](../../docs/adr/0056-workload-values-in-ai-helm-values.md), the
`security-policies` app's `valuesObject` — hosts, the full AuthConfig
(authentication/metadata/authorization/response), the Authorino instance spec,
and the SecurityPolicy target — was moved out of `charts/apps/values.yaml` into
the **private** `ai-helm-values` repo at
`environments/prod/values/security-policies.yaml`. `charts/apps/values.yaml`
only carries the app's chart source (`valuesFromRepo: true`) and deps overlay
wiring. This chart holds *how to render*; `ai-helm-values` holds *what is
deployed*. See the repo's root [`CLAUDE.md`](../../CLAUDE.md) "ai-helm ↔
ai-helm-values" section for the full split.

## `authConfigs.<name>` — AuthConfig shape

```yaml
authConfigs:
  main:                              # → AuthConfig kuadrant-policies-main
    hosts: [api.ai.camer.digital]
    when: [ ... ]                    # optional — see "Top-level `when`" below
    serviceAccountClients: [ ... ]   # chart-private, see "_skipForServiceAccounts"
    authentication: { ... }          # passed through as-is (toYaml)
    metadata: { "<step-name>": { ... } }      # per-entry, honors _skipForServiceAccounts
    authorization: { "<step-name>": { ... } } # per-entry, honors _skipForServiceAccounts
    response: { ... }                # passed through as-is (toYaml)
```

`hosts`, `authentication`, and `response` are rendered verbatim (`toYaml`) —
whatever Authorino's `AuthConfigSpec` accepts there is accepted here unchanged.
`metadata` and `authorization` are rendered **per-entry** instead of as one
block, so the `_skipForServiceAccounts` helper (below) can rewrite individual
steps without touching the rest.

### Top-level `when`

`spec.when` is Authorino's **overall gate** for the AuthConfig: a list of
`PatternExpressionOrRef` predicates evaluated *in addition to* `hosts`, before
any authentication/metadata/authorization step runs. If omitted, the AuthConfig
applies to every request that matches its `hosts`. If present, **all**
conditions must match, or Authorino skips the whole AuthConfig and lets the
request through with status OK (as if no AuthConfig existed for it) — this is a
resource-level bypass, not a 403.

```yaml
authConfigs:
  main:
    hosts: [api.ai.camer.digital]
    when:
      - selector: request.method
        operator: neq
        value: OPTIONS               # don't force preflight requests through auth
```

This is a **different mechanism** from the per-step `when:` blocks the
`_skipForServiceAccounts` helper injects into individual `metadata`/
`authorization` entries (see next section) — the top-level one gates the entire
AuthConfig; the per-step one gates a single step within an AuthConfig that
still runs authentication and every other step normally. Set `when` at this
level only for conditions that should exempt a request from **all** auth (rare
— most conditional logic belongs in a per-step `when:` or the
`_skipForServiceAccounts` marker instead).

### `_skipForServiceAccounts` — per-step SA bypass

Historical mechanism from the pre-[ADR-0021](../../docs/adr/0021-burst-budget-billing-and-dual-plane-authconfigs.md)
OPA era, kept inert for possible future burst-control use. Full writeup:
[`docs/patterns/authorino-service-account-bypass.md`](../../docs/patterns/authorino-service-account-bypass.md).
Summary:

- `serviceAccountClients: [clientId, ...]` on an AuthConfig entry is the
  allowlist of Keycloak SA client IDs.
- Any `metadata.<step>` or `authorization.<step>` entry marked
  `_skipForServiceAccounts: true` gets `when: [{selector: auth.identity.azp,
  operator: neq, value: <client>}, ...]` appended (one predicate per
  allowlisted client, AND'd) — the step then only runs for tokens whose `azp`
  is NOT in the list, i.e. non-SA (human) callers.
- The marker itself is stripped before rendering; Authorino never sees it.
- If the step already has a user-supplied `when:`, the SA-exclusion predicates
  are **appended**, not replacing it.
- Only honored on `metadata` and `authorization` entries — not on
  `authentication` or `response` (see the doc's "Known limitation").

## `instances.<name>` — Authorino operator instance

```yaml
instances:
  default:                           # → Authorino kuadrant-policies-default
    replicas: 2                      # HA — every gateway request hits Authorino
    supersedingHostSubsets: true     # let a "*" catch-all coexist with specific hosts
    listener: { ... }                # verbatim
    oidcServer: { ... }              # verbatim
    volumes: { ... }                 # verbatim
```

`supersedingHostSubsets: true` is required for a deny-all catch-all AuthConfig
to coexist with more specific per-host AuthConfigs — the most-specific host
wins (ADR-0021).

## `securityPolicies.<name>` — attach Authorino to the Gateway

```yaml
securityPolicies:
  main:                              # → SecurityPolicy kuadrant-policies-main
    gatewayName: core-gateway
    authorinoService: kuadrant-policies-default-authorino-authorino-authorization
    sectionNames: [api-https, api-internal]   # default: [api-https]
```

Emits one `targetRefs` entry **per listener** in `sectionNames`. This matters:
a `SecurityPolicy` that only targets `api-https` leaves any other listener
(e.g. `api-internal`) with **no ext_authz filter at all** — traffic on that
listener bypasses Authorino entirely (no JWT check, no `x-oidc-*`/
`x-account-id` stamping). Drive `sectionNames` from every listener that needs
auth, not just the historical default.

## `repoAuthInternalSecret` — GitHub OIDC repo-binding token

```yaml
repoAuthInternalSecret:
  enabled: true
  secretName: lightbridge-repo-auth-internal   # default
  secretStore: ssegning-aws                    # default
  remoteKey: ai/camer/digital/prod/env         # default
  property: repo_auth_resolve_internal_token   # default
  refreshInterval: 1h                          # default
```

The `X-Internal-Token` Authorino presents to `lightbridge-repo-auth`'s
`/v1/resolve` when validating a GitHub Actions OIDC token
([ADR-0047](../../docs/adr/0047-github-oidc-repo-binding-for-ci.md)). Referenced
by an AuthConfig's `metadata` step via `sharedSecretRef`.

> ⚠️ **Ordering hazard.** This Secret must exist **before** the AuthConfig that
> references it via `sharedSecretRef` is applied. A missing secret makes the
> whole AuthConfig fail readiness → Authorino drops every host it covers →
> **gateway-wide 404** — the exact failure mode that forced the 2026-06-04 OPA
> removal (see [`docs/architecture/05-auth-identity.md`](../../docs/architecture/05-auth-identity.md)).
> The `remoteKey`/`property` must already exist in `ssegning-aws` before this
> is enabled.

## Verifying

```bash
helm dep build charts/kuadrant-policies
helm lint charts/kuadrant-policies --strict
helm template kuadrant-policies charts/kuadrant-policies -f /tmp/sample-values.yaml
```

Where `/tmp/sample-values.yaml`:

```yaml
authConfigs:
  main:
    hosts: [api.ai.camer.digital]
    when:
      - selector: request.method
        operator: neq
        value: OPTIONS
    serviceAccountClients: [adorsys-gis-github-ci]
    authentication:
      keycloak:
        jwt:
          issuerUrl: https://keycloak.example/realms/camer-digital
    metadata:
      lightbridge-validation:
        _skipForServiceAccounts: true
        http: { url: https://example/resolve }
    response:
      success:
        headers:
          x-account-id: { plain: { value: test } }
instances:
  default:
    replicas: 2
    listener: { ports: { grpc: 50051, http: 8080 } }
    oidcServer: { ports: { https: 8443 } }
securityPolicies:
  main:
    gatewayName: core-gateway
    authorinoService: kuadrant-policies-default-authorino-authorino-authorization
    sectionNames: [api-https, api-internal]
```

To check against the **live production shape** (which lives in the private
`ai-helm-values` repo, not here):

```bash
helm template kuadrant-policies charts/kuadrant-policies \
  -f <path-to-ai-helm-values>/environments/prod/values/security-policies.yaml \
  | yq '.spec'
```

## Related

- [`docs/patterns/authorino-service-account-bypass.md`](../../docs/patterns/authorino-service-account-bypass.md) — full `_skipForServiceAccounts` writeup + testing recipe.
- [`docs/architecture/05-auth-identity.md`](../../docs/architecture/05-auth-identity.md) — current auth model narrative (dual-plane, descriptors, MCP carve-out).
- [`docs/architecture/03-gateway-components.md`](../../docs/architecture/03-gateway-components.md) · [`02-containers.md`](../../docs/architecture/02-containers.md) — where this chart sits in the gateway stack.
