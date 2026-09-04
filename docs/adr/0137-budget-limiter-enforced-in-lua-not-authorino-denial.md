# ADR-0137: The budget limiter refuses in Lua, because Authorino's denial status is one constant per AuthConfig

- Status: Proposed
- Date: 2026-09-03
- Deciders: @stephane-segning
- Source of truth: [lightbridge-authz#658](https://github.com/ADORSYS-GIS/lightbridge-authz/issues/658)
  (the decision memo) and **lightbridge-authz ADR-0034** (`docs/adr/0034-dynamic-budget-limiter.md`
  in that repo), which owns the design end to end. This ADR records only the gateway-side decision
  and the evidence behind it.
- Builds on: [ADR-0111](./0111-calendar-aligned-billing-period.md) (the billing-period Lua and the
  one-EnvoyExtensionPolicy-per-targetRef constraint), [ADR-0133](./0133-enforce-model-allowlist-in-a-gateway-lua-filter.md)
  (the same filter, the same `pcall` guard, the same harness shape), [ADR-0116](./0116-redaction-as-ext-proc.md)

## Context

A budget refill changes the ledger and nothing else: the gateway enforces two static Envoy
rate-limit rules whose limits come from Helm values, and no rule keys on anything a refill moves.
lightbridge-authz ADR-0034 fixes that by having Authorino ask `authz-budget` for the account's
**live** balance (an AuthConfig `metadata` step against a new mTLS-only
`GET /budget/v1/remaining`) and publish it as ext_authz **dynamic metadata**.

That leaves one gateway-side question: **who turns "remaining <= 0" into a 402?**

The obvious answer — and the one asked for explicitly — is Authorino itself: an `authorization`
rule on the metadata result, plus `response.unauthorized` returning 402 with a CEL-built JSON body.
It was evaluated against the **deployed** CRD, not upstream source.

## Evidence, from the running cluster (2026-09-03)

```console
$ kubectl -n authorino-system get deploy authorino-operator \
    -o jsonpath='{.spec.template.spec.containers[*].image}'
quay.io/kuadrant/authorino-operator:v0.23.1

$ kubectl -n converse-gateway get deploy kuadrant-policies-main \
    -o jsonpath='{.spec.template.spec.containers[*].image}'
quay.io/kuadrant/authorino:v0.24.0

$ kubectl explain authconfigs.spec.response.unauthorized \
    --api-version=authorino.kuadrant.io/v1beta3
FIELDS:
  body    <Object>     HTTP response body to override the default denial body.
  code    <integer>    HTTP status code to override the default denial status code.
  headers <map[string]Object>
  message <Object>

$ kubectl explain authconfigs.spec.response.unauthorized.body \
    --api-version=authorino.kuadrant.io/v1beta3
FIELDS:
  expression <string>   A Common Expression Language (CEL) expression ...
  selector   <string>   Simple path selector ...
```

So `body`, `message` and `headers` **are** per-request expressions — the 402 body the design wants
is natively expressible. `code` is a **plain `<integer>`**: not a `ValueOrSelector`, no
`expression`, no `selector`. It is one constant for the whole AuthConfig, and Authorino has exactly
one `response.unauthorized` per AuthConfig (no per-rule denial spec).

The prod `main` AuthConfig already denies for **four** unrelated reasons, all of which return 403
today and must keep doing so (`ai-helm-values/environments/prod/values/security-policies.yaml`):

| Rule | Denies when | Correct status |
|---|---|---|
| `repo-binding-allowed` | a GitHub token's repo is not bound | 403 |
| `keycloak-requires-email` | a `client_credentials` token reaches the human plane | 403 |
| `lightbridge-key-active` | the presented API key has been revoked | 403 |
| `lightbridge-model-allowed` | `model_policy: deny_all` / an unrecognised value | 403 |

Setting `code: 402` to make budget exhaustion a 402 turns *"your key was revoked"* and *"that model
is not allowed for this project"* into `402 Payment Required`. That is not cosmetic: 402 is the
status every client will be taught to read as "top up and retry", and it would then fire on
conditions no payment can fix. The AuthConfig is selected by Host and the hosts are fixed, so there
is no second AuthConfig to put the budget rule in.

While confirming the above, one more deployed-CRD fact settled a contradiction the values repo
carries in a comment:

```console
$ kubectl explain authconfigs.spec.metadata.http.timeout \
    --api-version=authorino.kuadrant.io/v1beta3
error: field "timeout" does not exist
```

`security-policies.yaml`'s note (*"authorino.kuadrant.io/v1beta3 has NO metadata.http.timeout
field"*) is **correct for v0.24.0**; upstream `main`'s Go types are ahead of the deployed release.
The budget metadata call therefore cannot bound its own latency, and must be bounded at the
`SecurityPolicy`'s `extAuth` instead.

## Decision

**The refusal is issued by a Lua filter on this Gateway, and Authorino adds no new `authorization`
rule.** Authorino does identity, the existing authorization rules, the `metadata` call and the
`dynamicMetadata` export; `charts/core-gateway/files/budget-limiter.lua` reads the metadata and owns
the status code.

Concretely:

- **A third `lua` entry** on the single `EnvoyExtensionPolicy` this Gateway may have (ADR-0111's
  header note; a second policy on the same targetRef is rejected `Conflicted` and silently never
  attaches). Filter order is `12 + index`, so: billing-period 12, model-policy 13, budget-limiter
  14 — all after ext_authz (5), which is what publishes the metadata.
- **Gated on `budgetLimiter.enabled`, default `false`.** With the default, the block renders
  nothing; prod's rendered manifests are unchanged except the chart-version label.
- **`budgetLimiter.shadowMode` defaults to `true`.** The filter computes and records its decision on
  every request and refuses nothing. Enforcement must be an explicit value in the values repo, never
  something a chart default can do on a promotion. The shipped `.lua` makes the same choice when its
  config table is missing entirely, and the harness proves it.
- **`extAuth.failOpen` becomes settable** on `SecurityPolicy` (rendered only when explicitly set, so
  the default output is unchanged). It has always been `false` by omission; the values repo now
  *asserts* it, because the value of this enforcement evaporates if a slow Authorino means "allow".

**Revisit this the day Authorino makes `code` a `ValueOrSelector`, or adds per-rule denial specs.**
The native path is strictly simpler and the Lua should be deleted for it. The exact YAML is kept in
lightbridge-authz ADR-0034 §14 so that change is a copy-paste, not a redesign.

## Consequences

- **Good.** The four existing denials keep their correct 403. The 402 carries a per-request JSON
  body (account id, `next_reset_at`, refill URL) built in the filter, which the native path could
  also have done. `pcall` converts Envoy's fail-**open** Lua-error default into a refusal, and
  `tests/budget-limiter/run.sh` proves the guard is load-bearing by running an unguarded copy on its
  own listener.
- **Bad.** Enforcement logic now lives in two places on this Gateway (model policy and budget), both
  in Lua, both dependent on Authorino having run first. That dependency is structural (EG's fixed
  filter order), not conventional, but it is still a coupling a reader has to know about.
- **Bad.** A Lua filter is harder to observe than an Authorino rule: decisions land in the
  `lightbridge.budget_limiter` dynamic-metadata namespace rather than in Authorino's own metrics.
  Shadow mode's whole output is that namespace, so it has to be scraped deliberately.

## Verification

`tests/budget-limiter/run.sh` replays the shipped `.lua` byte-for-byte through
`envoyproxy/envoy:distroless-v1.38.3` — the image the prod data plane runs — across five listeners
(enforce, shadow, no-config, fault-injected, fault-injected-with-the-guard-removed), with a fake
metadata source standing in for Authorino. 18/18 pass. See that script's header for what each
listener proves.

## Amendment, 2026-09-03: a Lua filter has to satisfy TWO runtimes, and only one of them is Envoy

Shadow mode was enabled (ai-helm-values#366) and the gateway answered `500` at ~20/min within a
minute, twice. Rolled back in ai-helm-values#367; recorded in ai-helm-values#368.

The access-log row said everything and named nothing:

```text
response_code                      500
response_code_details              direct_response      ← a ROUTE answered, not a filter
response_flags                     -
upstream_transport_failure_reason  -
budget_decision                    -                    ← record() never ran
```

`direct_response` is `StreamInfo::ResponseCodeDetails::DirectResponse` — the router serving a route
whose action is a direct response. No Lua filter produced it. `kubectl logs … -c envoy | grep -i
lua` was empty for the same reason: **Envoy never loaded the script at all.**

**Envoy Gateway executes an inline `lua` entry in its own controller before it ever reaches the data
plane.** `internal/gatewayapi/luavalidator` runs the script in gopher-lua against mock stream
handles, with `envoy_on_request(StreamHandle)` appended; `LuaValidation: Strict` is the default and
this chart does not set `EnvoyProxy.spec.luaValidation`. Its `security.lua` sandbox **nils**
`rawget`, `rawset`, `setmetatable`, `getmetatable`, `load`, `loadstring`, `require`, `dofile`,
`loadfile`, `package`, `debug` — and `_G`.

`budget-limiter.lua` opened with `local CONFIG = rawget(_G, "BUDGET_LIMITER_CONFIG") or {}`, a
defensive read against a metatable that Envoy's Lua filter does not put on the global table. Under
the sandbox it is `nil(nil, "…")`:

```text
Lua: validation failed for lua body in policy with name
  envoyextensionpolicy/envoy-gateway-system/core-gateway-billing-period/lua/2:
  failed to validate with envoy_on_request: <string>:71: attempt to call a non-function object
```

And the blast radius is the whole Gateway, not the one filter —
`internal/gatewayapi/envoyextensionpolicy.go`:

> *Lua extension doesn't have a fail open option, so fail the route if there is a lua error*

every route on the targeted Gateway gets `DirectResponse{StatusCode: 500}`. Public plane and
internal plane alike; the internal plane was simply the chattiest caller in the sample.

**The bisect that settled it** (`egctl x translate v1.8.2` over the chart rendered at the incident's
own prod values, one axis per landed PR):

| | access-log fields absent | access-log fields present (#1097) |
|---|---|---|
| **third `lua` entry absent** | `Accepted: True`, no 500 | `Accepted: True`, no 500 |
| **third `lua` entry present (#1095)** | `Accepted: False`, route → 500 | `Accepted: False`, route → 500 |

#1097's four `%DYNAMIC_METADATA(lightbridge.budget_limiter:…)%` operators are **not** implicated in
either direction. The two PRs shared one values gate (`budgetLimiter.enabled`), which is the only
reason they were ever confounded.

### What changed

- The line is a plain global read. Envoy's Lua filter puts no `__index` on the global table, so it
  is equivalent there, and it survives the controller too. It stays a plain read.
- **`tests/envoy-gateway-lua/run.sh`** runs EG's real translator over the rendered chart and fails on
  a non-`Accepted` policy or any route rewritten to a 500 — for every `lua` entry, in shadow *and*
  enforcing renders, so Stage 3's flip is proven today rather than on the night it ships.
  `tests/budget-limiter/run.sh` calls it first.
- **(2026-09-04 follow-up) The gate carries a permanent negative control, and the data-plane
  harness now asserts the access log.** `tests/envoy-gateway-lua/check.py` re-injects the exact
  `rawget(_G, …)` line into the rendered policy on every run and requires the translator to reject
  it with the full incident signature (`Accepted: False` *and* the probe route rewritten to 500) —
  a gate that cannot fail is not a gate. `tests/budget-limiter/` replays the chart's *own* rendered
  access-log `format.json` + `matches` predicate (the four `budget.*` fields of #1097 included) and
  the metadata shapes both prod AuthConfigs publish, and proves over every row it logs that a
  refusal made inside this filter is `response_code_details: lua_response`, an allowed request is
  `via_upstream`, and `direct_response` + 500 — the incident's signature — is unreachable from any
  path through the script, including a raise inside or outside the `pcall` guard.

### The lesson worth keeping

Eighteen real-Envoy behaviour tests passed against a script that could not be admitted to a cluster.
`helm template` renders a Lua body as an opaque string; `helm lint` does not read it; a data-plane
harness starts *after* the only component that rejects it. **A test that exercises the data plane
cannot validate control-plane admission** — the same shape as the CEL defect six minutes earlier
(ai-helm-values#365), where only Authorino could type-check the expression. Both now have a gate
that runs the real validator.
