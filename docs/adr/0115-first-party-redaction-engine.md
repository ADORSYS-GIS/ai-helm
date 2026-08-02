# ADR-0115: Build the redaction proxy ourselves; retire censgate/redact

**Status:** Accepted
**Date:** 2026-08-02
**Deciders:** @stephane-segning

## Context

[ADR-0113](./0113-redaction-front-proxy-not-ext-proc.md) chose a **front
proxy** over an Envoy `ext_proc` filter, and chose
[`censgate/redact`](https://github.com/censgate/redact) off the shelf to be
that proxy. The front-proxy half of that decision stands and is not revisited
here. The engine half does not survive contact with the artifact.

**The published image cannot execute.** Post-merge verification of
[#889](https://github.com/ADORSYS-GIS/ai-helm/pull/889) found the deployment
reconciled cleanly — Service, Deployment, Certificate and
`CiliumNetworkPolicy` all `Synced` — and the pod then `CrashLoopBackOff`ed
immediately:

```
/usr/local/bin/redact-gateway: /lib/x86_64-linux-gnu/libc.so.6:
version `GLIBC_2.38' not found (required by /usr/local/bin/redact-gateway)
```

Their builder stage links against a newer glibc than their
`gcr.io/distroless/cc-debian12` runtime ships. Reproduces with a bare
`docker run`; every published tag (`latest`, `0`, `0.9`, `0.9.0`) resolves to
the same broken digest. Filed as
[censgate/redact#114](https://github.com/censgate/redact/issues/114); the
canary was paused in [#890](https://github.com/ADORSYS-GIS/ai-helm/pull/890).

That is not a bug to wait out — it is evidence about process. The project's
top committers are `cursoragent` (47 commits), `censgate-mark` (45),
`f1r32025` (38), `claude` (18) and `censgate-coder` (13), plus bots; recent
commits are authored by "Cursor Agent" and merged by `cursor[bot]`. They wrote
a README section to "lead with" a release nobody ran. **A binary in the
fail-closed path of every AI request has to be one we build, test and can
fix.**

## Decision

**Build the redaction proxy as a first-party service** — `redact-gateway` in
`ADORSYS-GIS/lightbridge-governance` — and **delete
`charts/censgate-redact-gateway`**.

Detection is delegated to the [`pii`](https://crates.io/crates/pii) crate
(worka-ai, MIT OR Apache-2.0). That is a materially different dependency
proposition from a whole gateway: text in, spans out; no network, no process
supervision, no release engineering of ours riding on it. If it stalls we
vendor or replace it without touching the request path. The policy — which
entities matter, what happens to them, and what happens when detection fails —
is ours.

What we own on top of the library:

- **A first-party credential recognizer pack.** `pii`'s `EntityType` has **no
  secrets category**, which for an AI gateway is the wrong way round: the
  highest-value thing to stop is a key pasted into a prompt bound for a
  third-party provider. Nine prefix-anchored patterns, anchored on distinctive
  literals rather than entropy so they do not fire on every checksum.
- **Profiles tuned for the traffic this gateway actually carries.**
  `coding-assistant` **blocks** credentials outright and deliberately
  **allows** `Url`/`Domain`/`Hostname`/`Uuid` — upstream scores those 0.5–0.7
  on regexes matching anything dotted, so in opencode/Kilo-Code/LibreChat
  traffic they fire on every import and file path.
- **Buffered SSE redaction.** [#875](https://github.com/ADORSYS-GIS/ai-helm/issues/875)
  measured 7 days of live traffic: opencode and Kilo-Code stream by default on
  both planes, so a buffered-only redactor was never optional. Buffering buys
  the property incremental cannot — detection sees complete text, so no entity
  can hide in a token split.
- **Fail-closed on every indeterminate branch**, including the unglamorous ones
  (unparseable body, unreadable upstream response).

**Person-name detection is not included and is not claimed.**
`Person`/`Location`/`Organization` come only from NER, and `pii`'s
`candle-ner` feature ships a `CandleNerModel` *trait* and an adapter — not a
model. `Profile::detects_names()` returns `false`, is tested, and is logged at
startup, so nothing downstream can assume coverage we lack.

**NER, when it lands, is a separate service**, not a dependency of this one.
Measured: adding candle in-process takes the proxy from 33 crates to 130 even
with `hf-hub` and `candle-examples` excluded, and pulls `esaxx-rs` (C++) via
`tokenizers`, which no feature flag removes. That is the wrong trade for the
component we are building specifically to reduce risk.

## Consequences

**Positive**
- We can fix it. The failure that killed the previous choice was unfixable by
  us and remains unfixed upstream.
- The scan surface is honest: a separate image means Trivy's result for the
  proxy reflects the proxy, not the governance API's `aws-sdk-s3`/`sqlx` tree.
- Detection quality becomes measurable and improvable rather than inherited —
  the secrets pack and the profile tuning are both things only we can know.
- Reuses the chart wiring already proven on the live cluster during the
  censgate canary; that deployment reconciled correctly, only its image was
  broken.

**Negative**
- We now maintain a service in the fail-closed path of every AI request. That
  is the cost of the decision, and it is not small.
- `pii` is 0.1.0, one author, no release since 2026-01. Acceptable as a bounded
  library we can vendor; it would not be acceptable as a binary in this
  position — which is precisely the distinction this ADR turns on.
- Buffered streaming means time-to-first-token becomes time-to-last-token for
  any client routed through the proxy. Real, and paid by streaming clients.

**Neutral / follow-ups**
- Incremental streaming mode (hold-back window) is a config-level addition if
  latency turns out to matter more than completeness.
- NER as a separate service needs its own ADR and epic.
- Cutting a real client over is still separate, reviewed work — see #873/#876.
  This ADR replaces the engine, not the rollout plan.

## Alternatives considered

- **Wait for censgate/redact#114 to be fixed** — rejected. It fixes one bug,
  not the process that shipped an unrunnable flagship release, and leaves a
  third party's binary fail-closed in front of every AI request.
- **Fork censgate/redact** — rejected. Inherits a large AI-authored codebase we
  would have to understand fully to trust, for less than we get from wrapping a
  focused library.
- **Use `redact-core` (their library) instead of `pii`** — reasonable and not
  ruled out on quality; `pii`'s validator-backed recognizers (Luhn, IBAN, SSN,
  ITIN, routing, IMEI) are real validation rather than regex alone, which is
  the better base. Revisit if `pii` stalls.
- **NER in-process now** — rejected on measurement; see the Decision.

## Related

- Supersedes the **engine choice** of [ADR-0113](./0113-redaction-front-proxy-not-ext-proc.md);
  its front-proxy-over-`ext_proc` decision **stands**.
- Chart/code: `ADORSYS-GIS/lightbridge-governance` (`charts/redact-gateway`,
  `crates/governance-redact`, `app/redact-gateway`)
- Deletes: `charts/censgate-redact-gateway`
- Epic [#873](https://github.com/ADORSYS-GIS/ai-helm/issues/873), story
  [#876](https://github.com/ADORSYS-GIS/ai-helm/issues/876), evidence
  [#875](https://github.com/ADORSYS-GIS/ai-helm/issues/875)
- Upstream defect: [censgate/redact#114](https://github.com/censgate/redact/issues/114)
