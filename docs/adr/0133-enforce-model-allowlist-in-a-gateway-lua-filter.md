# ADR-0133: Enforce the per-project model allowlist in a gateway Lua filter, not in Authorino

**Status:** Proposed
**Date:** 2026-08-22
**Deciders:** @stephane-segning

## Context

`lightbridge-authz` ADR-0018 gave every project a `model_policy` enum — `allow_all`,
`allowlist`, `deny_all` — plus an `allowed_models` list, and made `deny_all` reachable by
inverting the old "empty list means everything" rule: under `allowlist`, an **empty list
permits nothing**.

[ai-helm-values#288](https://github.com/ADORSYS-GIS/ai-helm-values/pull/288) split
enforcement of that enum in two, at the repo owner's direction: *"For the allowed_models, I
think we can simply pass the list downstream from OPA and validate it at model level direct
(is model in list of allowed model) and we move the computation elsewhere."* Authorino kept
the half that needs no model name — it denies `deny_all` and every unrecognised value at the
edge — and publishes the rest as two request headers, `x-model-policy` and
`x-allowed-models`, on every success path of both AuthConfigs. Two reasons drove the split:
the CEL predicate had to depend on `x-ai-eg-model`, which cost it two fail-open escape
hatches, and two CEL-evaluation incidents in one afternoon (ai-helm-values#290 → #291)
argued for shrinking what runs inside a CEL predicate, not growing it.

That left `allowlist` **published but unenforced**: the list rode on every request and no
component read it, so a project restricted to one model could call any model in the
catalogue. This ADR decides where the missing consumer lives.
Ticket: <https://github.com/ADORSYS-GIS/ai-helm-values/issues/292>.

## Decision

**Enforce list membership in a Lua HTTP filter on `core-gateway`, added as a second `lua`
entry on the existing Gateway-scoped `EnvoyExtensionPolicy`.** The script lives at
`charts/core-gateway/files/model-policy.lua` and is embedded verbatim via `.Files.Get`.

It reads `x-model-policy` **first** — the list alone is ambiguous, since `""` means
"everything" under `allow_all` and "nothing" under `allowlist` — and applies:

| `x-model-policy` | `x-ai-eg-model` | outcome |
| --- | --- | --- |
| absent | absent | allow — not a model request, and no policy context to apply |
| absent | present | **deny** — a model request that never passed the AuthConfig that stamps the policy |
| `""` | any | allow — internal plane, no project context |
| `allow_all` | any | allow — the list is ignored |
| `allowlist` | absent or empty | **deny** — the model cannot be determined |
| `allowlist` | in the list | allow |
| `allowlist` | not in the list, or list empty | **deny** |
| anything else | any | **deny** |
| any input header sent twice | any | **deny** |
| the script itself raises | any | **deny** (`pcall` guard) |

Refusals are `403` with an OpenAI-shaped error body naming the model.

Three properties are load-bearing, and each is there because of something measurable:

- **Position.** Envoy Gateway v1.8.2 fixes the order of every filter it generates
  (`internal/xds/translator/httpfilters.go`, `newOrderedHTTPFilter`): ext_authz is 5, Lua is
  `12 + index`, EnvoyExtensionPolicy ext_proc is `100 + index`. The AI Gateway's own
  ext_proc is injected ahead of that table entirely (observed as filter 1 on the external
  chain). So this filter is order 13 and is *structurally* guaranteed to run after both the
  processor that sets `x-ai-eg-model` and the ext_authz that stamps the policy headers. It
  is not a matter of luck or of which chain the request took.
- **Fail-closed.** Envoy's default for an uncaught Lua error is to log it and continue the
  filter chain — fail **open**. The script therefore wraps its whole body in `pcall` and
  refuses on any raise. This was verified by running the shipped script with a fault
  injected, twice: with the guard the request is refused, with the guard removed the request
  reaches the upstream.
- **Duplicate-header refusal.** Envoy's Lua `headers:get()` concatenates duplicate entries
  with `,`. A client-supplied second `x-allowed-models` therefore *widens* the list that
  membership is tested against. The first version of this script allowed exactly that, on
  the deployed Envoy image, which is how the check came to exist.

## Consequences

**Positive**

- `allowlist` becomes a real state instead of an advisory one, including the ADR-0018
  empty-list inversion, which is the case most likely to be implemented backwards.
- Enforcement sits at the only point that owns both facts, and owes nothing to CEL. The
  authorization layer keeps the smaller surface #288 gave it.
- The deployed bytes are testable bytes: `tests/model-policy/run.sh` replays the chart's own
  `.lua` file through `envoyproxy/envoy:distroless-v1.38.3`, the exact data-plane image, and
  a rendering assertion pins the embedded copy to the file.
- Header spoofing is refused twice over — by Authorino's `headers_to_set` overwrite upstream,
  and by this filter's duplicate-header check locally, which does not depend on that
  upstream guarantee holding.

**Negative**

- A project on `allowlist` is refused on requests carrying **no** model at all — e.g. a
  `GET /v1/models` on the same host. That is the deliberate direction of the fail-closed
  rule ("cannot determine the model ⇒ refuse"), and it is a no-op while every project is on
  `allow_all`, but it is a real behaviour change the first time a project is moved to
  `allowlist`. The alternative — allowing when no model is present, on the grounds that no
  AIGatewayRoute rule can match without `x-ai-eg-model` — was rejected as too clever a thing
  to rest an enforcement point on.
- Envoy Gateway accepts exactly one `EnvoyExtensionPolicy` per targetRef, so this shares the
  Gateway-scoped policy with the billing-period Lua and runs on **every** route of **both**
  listeners, including the MCP routes that carry their own SecurityPolicy and the two
  unauthenticated model-catalog paths. Handling those is what the "policy absent + model
  absent ⇒ allow" row is for; it is not a free choice, it is forced by the attachment scope.
- Lua in a values-repo-invisible chart file means changing enforcement needs an ai-helm chart
  release, not an ai-helm-values commit. That is the right trade for a safety invariant (same
  reasoning as `failOpen: false` being hardcoded on the redact ext_proc), but it is slower.

**Neutral / follow-ups**

- The filter writes `lightbridge.model_policy` dynamic metadata (`decision`, `reason`) on
  every request. Nothing consumes it yet; promoting `reason` into the access log would give a
  free "who is being refused, and why" board.
- Confirm no project is on `model_policy = allowlist` before the chart release reaches prod,
  so the first deploy is provably a no-op. This cannot be read from cluster config — it is a
  `projects` row — so it needs an operator query.

## Alternatives considered

- **Keep it in Authorino's CEL predicate** — where it was before #288. Rejected by the owner
  and by evidence: it forces the auth layer to depend on `x-ai-eg-model` (which cost two
  fail-open escape hatches), and two CEL incidents in one afternoon argued for shrinking that
  surface. Also structurally wrong on the internal chain, where ext_authz runs first.
- **The Envoy AI Gateway ext_proc** — the ticket's own first suggestion, since it already
  owns the parsed body and the model name. Rejected on ordering: it is injected *ahead* of
  Envoy Gateway's filter table and runs as filter 1 on the external chain, i.e. **before**
  Authorino, so at the time it processes a request the policy headers do not exist yet. It
  would also mean forking or wrapping an upstream component.
- **A native AIGatewayRoute matcher** — rejected: the CRD offers only
  `spec.rules[].matches[].headers[]` with `Exact`/`RegularExpression` against a *static*
  value. There is no way to express "this header's value must appear in that header's list",
  which is what a per-project allowlist needs.
- **A second EnvoyExtensionPolicy of our own** — rejected: Envoy Gateway rejects a second
  policy on the same targetRef outright (`Accepted: False, reason: Conflicted`), which is how
  ai-helm#900 shipped a redaction filter that was never attached at all.
- **A small ext_authz or ext_proc service** — rejected as disproportionate. It is a string
  membership test on three headers; a sidecar buys a network hop, a failure mode, an image to
  build and sign, and a `failOpen` decision, for logic that fits in 80 lines of Lua that can
  be tested in a container.
- **A `BackendTrafficPolicy` rule**, the way `x-quota-tier` / `x-billing-plan` are consumed —
  rejected: rate-limit `clientSelectors` throttle on an `Exact`/`Distinct` header match. They
  cannot express list membership, and throttling is not refusal.

## Related

- Ticket: <https://github.com/ADORSYS-GIS/ai-helm-values/issues/292>
- Upstream half: <https://github.com/ADORSYS-GIS/ai-helm-values/pull/288> (the truth table and
  YAML comments next to the header definitions are the contract this implements)
- `lightbridge-authz` ADR-0018 (the `model_policy` enum and the empty-list inversion),
  ADR-0019 / lightbridge-authz#418 (which made `allowlist` reachable)
- Charts/files touched: `charts/core-gateway/files/model-policy.lua`,
  `charts/core-gateway/templates/envoyextensionpolicy-billing-period.yaml`,
  `tests/model-policy/`
- Builds on [0111](./0111-calendar-aligned-billing-period.md) and
  [0116](./0116-redaction-as-ext-proc.md) — the same single `EnvoyExtensionPolicy`
