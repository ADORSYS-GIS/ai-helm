# Plan: Censgate Redact `ext_proc` on the AI Gateway

> `~/Downloads/envoy-censgate-redact-extproc-mvp-plan.md` assessed against the gateway
> that is actually running: **Envoy Gateway v1.8.2 + Envoy AI Gateway v1.0.0** (CRDs
> v1.0.0, lockstep per ADR-0069), Authorino ext_authz on two listeners, `charts/ai-model`
> rate-limit + cost CEL on top.
>
> Unlike the [Copilot](./github-copilot-governance.md) and
> [Foundry](./microsoft-foundry-governance.md) plans, this one touches the **production
> data path for every AI request in the org**. It is planned accordingly.

**Status:** Proposed plan · **Date:** 2026-07-31 · **Maintainer:** @stephane-segning

---

## 0. Two findings that should reshape the plan before anyone writes code

### Finding 1 — The MVP as scoped can never front production traffic

The scope freeze excludes `stream: true` and returns **HTTP 400** for it. Our production
traffic is overwhelmingly streaming: opencode and LibreChat both stream by default, and
the whole of [ADR-0034](../docs/adr/0034-restore-streaming-timeouts-and-extproc-headroom.md)
exists because long streaming generations were being cut mid-stream. Its own words about
the AI Gateway's processor: it "holds state for the whole stream."

So the MVP's exit criteria are all reachable — on a canary, against a mock provider — but
"migrate one non-critical application to the canary hostname" (§14) means migrating an
application that **does not stream**, and there may not be one. Everything real here
streams.

This isn't an argument against the MVP. It's an argument against the roadmap ordering:
**incremental SSE processing is not post-MVP item #1, it is the gate on any production
use whatsoever.** I'd restructure so the SSE design is settled during the MVP (even if
implemented after), rather than discovered at promotion time. Concretely: add "decide the
SSE strategy — incremental vs buffered-for-sensitive-profiles — and prove it on one
fixture" to Milestone 3.

### Finding 2 — Don't budget the fork until you've measured the ordering

§9 says "a standard `EnvoyExtensionPolicy` **may** not produce the required order" and
jumps to a pinned fork of Envoy AI Gateway. That hedge is doing a lot of work, and the
premise looks like it was written against a pre-1.0 AIEG.

What I could establish from upstream: AIEG attaches its own processor through the *same
public mechanism* — an `EnvoyExtensionPolicy` named `ai-eg-route-extproc-${name}` — not a
privileged hardcoded insertion. Envoy Gateway also exposes `EnvoyProxy.spec.filterOrder`
(`{name, before, after}`), and **we already ship an `EnvoyProxy` CR** at
`charts/core-gateway/templates/envoy-proxy.yaml`. The known gap is that `filterOrder`
matches on filter *name*, and two ext_proc instances share the `envoy.filters.http.ext_proc/…`
prefix — which is precisely what upstream
[envoyproxy/gateway#8789](https://github.com/envoyproxy/gateway/issues/8789) ("Add name
and statPrefix fields to EnvoyExtensionPolicy extProc") is about. So it may genuinely not
be expressible today. **But that is a measurement, not a deduction.**

This repo has an expensive precedent for exactly this mistake: the `/v1/models` filtering
verdict was written down as unfixable in two separate migration docs, three layers of
workaround were built on top of it, and the fix turned out to be one field
(`AIGatewayRoute.spec.hostnames`) that had shipped in the version already running.

**Spike first, one afternoon, before Milestone 5 is budgeted.** Deploy a no-op pass-through
ext_proc against the canary gateway and read `/config_dump` for each of:

| # | Configuration to try |
|---|---|
| a | `EnvoyExtensionPolicy` on the **Gateway** vs on the **HTTPRoute** (AIEG's is route-attached) |
| b | Two `extProc` entries in a **single** policy's `spec.extProc[]` list |
| c | `EnvoyProxy.spec.filterOrder` with `before: envoy.filters.http.ext_proc` |
| d | Whether creation timestamp / name sort decides ties |

If (a)–(d) all fail, file upstream against #8789 **and then** choose between the fork and
the alternative below — don't default to the fork.

### The alternative that sidesteps §9 entirely — and it is already written

[`censgate/redact`](https://github.com/censgate/redact) (Rust, Apache-2.0, v0.9.0) does
not just ship the traversal library this plan assumed. It ships **`redact-gateway`, an
OpenAI-compatible privacy proxy** — alongside `redact-core` (the library), `redact-cli`,
`redact-api` and `redact-wasm`. So the front-proxy option is not "write a reverse proxy,"
it is "deploy theirs":

```text
client → redact-gateway (off the shelf) → core-gateway (authorino → AIEG → provider)
```

No ext_proc protocol, no filter ordering, no fork, no new code. Precedent for the shape is
solid — `charts/mcp` renders per-MCP Caddy/openresty *normalizing proxies* for exactly this
"can't fix it at the Envoy layer" reason
([ADR-0040](../docs/adr/0040-external-mcps-via-caddy-normalizing-proxy.md)), and
`lakefs-proxy` is a first-party Rust reverse proxy already in production.

`redact-core` also covers the four MVP actions (replace / mask / hash, plus reversible
encrypt on the gateway), 54 pattern-based entity types, 18 secret/credential types, and
emits OpenTelemetry metrics — which is the actual deliverable here.

**Its real cost:** it sits **before** Authorino, so it has no authenticated identity, which
forecloses per-tenant policy profiles until it moves inside the filter chain. It also
processes unauthenticated traffic (a DoS surface the gateway currently absorbs) and needs
its own host + certificate.

**Recommended path given the stated priorities** — the product is the dashboard, and
per-tenant policy is "would be cool, not now":

1. **Deploy `redact-gateway` as the front proxy first.** It gets redaction, blocking and
   the trim-per-request metrics into Grafana with essentially zero build, and defers the
   ordering/fork question indefinitely.
2. **Treat `redact-extproc` as the upgrade** that unlocks per-tenant policy. When it's
   wanted, the build is "wrap `redact-core` in `tonic`" — not a redaction engine — and the
   ordering spike happens then, with a real requirement behind it.

⚠️ **Turn the ML NER off for any data-path deployment.** The ONNX transformer path
(PERSON/ORGANIZATION/LOCATION) means model download, significant memory, and variable
latency inside a `failOpen: false` hop. The 54 pattern-based recognisers cover the MVP's
entity list; add NER later behind measurement.

**On `EnvoyPatchPolicy`:** the spec is right to warn against it, and this platform agrees
from experience — ADR-0039's `EnvoyPatchPolicy` for MCP backend TLS was built, shipped,
found to have **zero effect**, and removed in ADR-0040. The `eg` app entry in
`charts/apps/values.yaml` now notes upstream issues affecting "EnvoyPatchPolicy/extension-server
users only, which we don't use." Endorsed — don't reach for it.

---

## 1. What forking AIEG actually costs here

If the spike says the fork is necessary, price it honestly before agreeing:

- AIEG is consumed as an **upstream OCI Helm chart pinned to `v1.0.0`**, with
  `aieg-crd` held in **lockstep** (ADR-0069). A fork means building and hosting our own
  controller image and re-basing it on every upstream bump — of the component that is the
  single point of failure for all AI traffic in the org.
- We are already carrying two upstream AIEG workarounds
  ([#2218](https://github.com/envoyproxy/ai-gateway/issues/2218) refero content-type,
  [#2219](https://github.com/envoyproxy/ai-gateway/issues/2219) firecrawl SSE) via the
  `charts/mcp` proxy engines, both explicitly labelled INTERIM pending upstream fixes.
  Adding a maintained fork on top changes the character of that debt.
- The maintainer's standing preference is hard cutovers over parallel paths, and no
  dormant code. A fork is the opposite: a permanent parallel path.

The post-MVP roadmap already lists "removal of the AI Gateway fork through an upstream
pre-AI-filter ordering capability" as item #8. If the fork is genuinely needed, **open
that upstream issue in Milestone 1, not at the end** — the fork's exit path should be in
flight the whole time it exists.

---

## 2. Where things go on this platform

| Spec says | Here |
|---|---|
| Namespace `ai-redact-mvp` | `redact-canary` (short-name convention) |
| Canary `Gateway` | **Internal** Gateway — ClusterIP, no Hetzner LB, no public DNS/cert. Precedent: core-gateway's `api-internal` listener + `templates/service-internal.yaml`, TLS from `self-signed-ca`. A second public Gateway means a second Hetzner LB (cost) and another ACME cert for no MVP benefit. |
| Raw Deployment/Service/ConfigMap YAML | `charts/redact-extproc` (bjw-template leaf, no own `templates/` ⇒ CI lints it non-strict) + `charts/redact-extproc-secrets` if needed; values in `ai-helm-values` |
| `NetworkPolicy` | **`CiliumNetworkPolicy`** — a plain `NetworkPolicy` `ipBlock` does not match on Cilium. New namespace ⇒ no default-deny baseline, so ship the restriction yourself. ⚠️ Must include `fromEntities: [host, remote-node, health]` or kubelet probes fail and it reads as a crash-loop. |
| `ServiceMonitor` | Yes — copy `charts/inference-server/templates/servicemonitor.yaml`. Metrics are pull-based here, not OTLP. |
| Dashboard | `tools/dashboards/src/dashboards/redact/*.py` → generated JSON, registered in `_DASHBOARD_MODULES`. Hand-written JSON fails `dashboards-drift`. Folder needs `resyncPeriod`. |
| Image | `ghcr.io/adorsys-gis/redact-extproc`, private ⇒ namespace-scoped `dockerconfigjson`; bjw-s resolves it from `defaultPodOptions.imagePullSecrets`, **not** `global.imagePullSecrets`. ⚠️ Build with `cargo-auditable` or Trivy scans zero crates and the green result is meaningless. |

**Policy ConfigMap reload gotcha.** The spec excludes hot reload, so a policy change needs
a pod roll — and on this platform `kubectl rollout restart` is **reverted by ArgoCD
selfHeal**. Use the repo's documented pattern: a generation counter in values feeding a
checksum annotation on the pod template, so the roll is declarative. (Also: mount the
ConfigMap as a directory, not `subPath` — subPath mounts don't update in place at all.)

---

## 3. Interactions with what's already on that path

These are not in the spec and each one is load-bearing:

1. **Authorino runs first (ext_authz, before any ext_proc).** So redaction always sees an
   authenticated request, and the ADR-0011 `x-oidc-*` headers plus the ADR-0021 rate-limit
   descriptors (`x-account-id`, `x-billing-plan`) are already stamped. That's the identity
   metadata post-MVP item #4 wants — available for free **if** redaction stays inside the
   filter chain. Another point on the ext_proc side of the §0 trade-off.
2. **Redacting before AIEG changes what gets billed.** AIEG's processor does token
   counting and the cost CEL (`charts/ai-model`), feeding the per-account monthly µ$
   budgets in redis. If redaction mutates the body first, the tokens counted are the
   *redacted* tokens — defensible, arguably correct, but it must be a stated decision
   because it silently changes the numbers on the cost dashboards. A blocked request
   never reaches AIEG at all, so it costs nothing and appears in no cost series — which
   is why `redact_extproc_blocks_total` matters as the only record.
3. **`failOpen: false` on the production gateway means a redactor outage is a total AI
   outage.** That is the correct security posture and I'd keep it — but two healthy
   replicas of a new Rust service become a hard dependency of everything. Give it a PDB
   from the start (the spec defers it), and treat its availability target as the
   gateway's.
4. **AIEG v1.0 ships built-in "request/response body redaction"** for observability. That
   is *not* what this MVP does (it doesn't stop data reaching the provider), but it may
   already satisfy the "no raw payloads in logs or traces" exit criterion — check before
   building anything for it.

---

## 4. On the code

I could not find a `censgate` or `redact` repo under `~/dev`, so this plan assumes the
"existing Redact request/response traversal" the spec refers to is real and lives outside
what's checked out here. Everything below is about the new `crates/redact-extproc` binary.

The house Rust baseline applies: `tonic`/`prost` for the ext_proc gRPC service, plus the
existing workspace idiom from `lightbridge-repo-auth` — `thiserror` at the library edge,
`anyhow` at the binary, `tracing-subscriber` with the `json` feature, `mimalloc`, and
`reqwest`/`rustls` if it needs egress. The spec's per-request-state struct and "do not log
or persist raw bodies" rule are exactly right; make it structural rather than
disciplinary — **wrap body types in a newtype whose `Debug`/`Display` print
`<redacted>`**, so a stray `tracing` field can't leak one. Test #11 ("raw payloads do not
appear in logs") then tests the type, not the reviewer.

The 12 unit tests and the four-message protocol sequence are a good list; keep them. The
one I'd add: **a fixture asserting that a request AIEG later rewrites (provider
translation) still round-trips correctly after body mutation** — that's the interaction
the mock-provider tests won't catch, because the mock speaks OpenAI natively and our
real backends include Anthropic and Google translations.

---

## 5. Sequencing

Milestones 1–4 and 6 stand as written. Two changes:

- **Milestone 0 (new, ~1 day):** the §0 Finding-2 ordering spike, plus the §2 inventory
  (which the spec rightly wants version-controlled — put it in
  `docs/migrations/2026-XX-XX-redact-extproc-canary.md`). Output: fork / no-fork / front-proxy.
- **Milestone 3 gains:** decide and prove the SSE strategy on one fixture. Not implement —
  decide, with evidence. Otherwise promotion discovers it.
- **Milestone 5** is conditional on Milestone 0 and may be deleted entirely.

ADR: one, covering the placement decision (ext_proc vs front-proxy), fail-closed, and the
billing interaction. Numbering follows whatever the governance ADRs take (0111+).

---

## 6. Open questions

1. **Is per-tenant policy the actual product?** If yes, ext_proc wins and §0's fork
   question must be answered properly. If the single static profile is genuinely enough
   for a year, the front-proxy is much cheaper and carries no upstream risk.
2. **Is there a non-streaming production client to canary with?** If not, §14's promotion
   gate can't be exercised as written and SSE moves into the MVP.
3. **Do we accept redacted-token billing** (§3.2), or should cost be computed pre-redaction?
4. **Where does Censgate Redact live**, and is the traversal library already usable as a
   Rust dependency?
5. **Is `failOpen: false` acceptable for the eventual production attach**, given it makes
   the redactor a hard dependency of all AI traffic — or does production want fail-open
   with an alert, accepting leakage during an outage?
