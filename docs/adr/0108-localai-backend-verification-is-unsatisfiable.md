# ADR-0108: LocalAI's backend signature verification is unsatisfiable — drop it, and correct the pinning claim

**Status:** Accepted
**Date:** 2026-07-29
**Deciders:** @stephane-segning

**Supersedes the *verification* decision of [ADR-0105](0105-pin-and-verify-the-localai-backend.md).**
ADR-0105's other decisions — the versioned gallery pin, defining the model
ourselves, and `download_files` sha256 weight pinning — stand unchanged.

## Context

ADR-0105 closed what ADR-0102 had left open: LocalAI resolves its inference
**backend** at runtime, separately from the server image, and both halves
floated. It pinned the gallery to `@v4.7.1`, declared the backend image tag
pinned to `v4.7.1`, and added a keyless-cosign `verification:` policy.

It also recorded, honestly, that the policy was **unproven**:

> **The cosign identity is unproven here.** The backend is already installed on
> the volume, so verification will not actually be exercised until a fresh
> volume. If the identity regex is wrong, that is when it fails — at the worst
> moment.

[ADR-0106](0106-restore-the-localai-image-tier.md) created exactly that fresh
volume, and flagged this as the top risk of merging. It fired within minutes of
the merge. The prediction was right; **the diagnosis in it was wrong**, and the
difference matters.

### What actually happened

```
Failed to download backend uri="quay.io/go-skynet/local-ai-backends:latest-gpu-nvidia-cuda-12-stablediffusion-ggml"
  error=cosignverify: no Sigstore bundle referrer for
        quay.io/go-skynet/local-ai-backends@sha256:84b0120a... (signed with --new-bundle-format?)
ERROR Backend not found  backend="stablediffusion-ggml"
ERROR LocalAI failed to start: failed to load model with internal loader: backend not found
```

`CrashLoopBackOff`, no Service endpoints — while `z-image-turbo-local` was
federated and advertised in `/v1/models`. The ADR-0101 failure mode again.

The identity regex was never reached. Checked against the registry rather than
inferred:

| Question | Answer |
|---|---|
| Is the backend image signed? | **Yes** — one referrer on the platform digest `sha256:84b0120a…` |
| In what format? | config `application/vnd.dev.cosign.artifact.sig.v1+json`, layer `application/vnd.dev.cosign.simplesigning.v1+json` — **legacy cosign** |
| What does LocalAI v4.7.1 verify? | a **new-format Sigstore bundle** referrer, as its own error hints |

**Upstream signs one way and its own verifier reads the other.** The policy could
not have succeeded regardless of issuer, regex or `not_before`. v4.7.1 is the
newest LocalAI release (2026-07-14), so there is no version to bump into, and no
upstream issue reports it.

### A second ADR-0105 claim that does not hold

ADR-0105's table says the backend **image tag** moved from `latest` to `v4.7.1`.
The env var is set correctly and LocalAI still pulled `latest-…`, because the
gallery index at `@v4.7.1` hardcodes the tag in the entry:

```yaml
- name: "cuda12-stablediffusion-ggml"
  uri: "quay.io/go-skynet/local-ai-backends:latest-gpu-nvidia-cuda-12-stablediffusion-ggml"
```

LocalAI uses that URI verbatim, so `--backend-images-release-tag` never applies
to a gallery-sourced backend. **The backend image tag was never pinned.** Today
`latest-…` and `v4.7.1-…` resolve to the same digest (`sha256:58bf31fe…`), so we
are running the bytes that were measured — but nothing holds that true tomorrow.

## Decision

**Remove the `verification:` block, and stop claiming a backend pin we do not
have.**

| | ADR-0105 said | Reality | Now |
|---|---|---|---|
| Backend gallery | pinned `@v4.7.1` | ✅ true, works | unchanged |
| Backend image tag | pinned `v4.7.1` | ❌ index hardcodes `latest` | **documented as unpinned**; knob kept (harmless, governs URIs LocalAI builds itself) |
| Signature check | keyless cosign | ❌ format mismatch, hard boot failure | **removed** |
| Weight bytes | sha256 per file | ✅ true, works | unchanged |

`requireBackendIntegrity` stays unset, and its status changes from *deferred* to
*load-bearing*: it rejects any backend install lacking a verification policy, and
since we cannot currently have one, setting it would hard-fail every boot.

The values file carries the full explanation inline, including an explicit "do
not re-add `verification:` expecting the regex to be the problem" — because the
next person to read ADR-0105 will reasonably assume exactly that.

**What we keep, and it is not nothing.** The model's weights remain sha256-pinned
via `download_files`; the gallery index remains version-pinned. What is lost is
signature verification of the backend **binary**, and with it — as note 2 above
makes explicit — any guarantee that the backend bytes do not change under us.

## Consequences

**Positive**

- Image generation boots again on a fresh volume.
- Two false claims are out of the documentation. ADR-0105's table asserted a pin
  and a verification that a reader would have relied on; neither held.
- The remaining exposure is written down where it is acted on, not only in an ADR.

**Negative**

- **The backend binary is unverified and unpinned.** LocalAI logs
  `installing OCI backend without signature verification` on every fresh install,
  and a `latest` tag means the bytes can change without any change on our side.
  This is a genuine supply-chain regression against ADR-0105's *intent*, though
  not against its *effect* — its effect was a crash loop.
- We are trusting quay.io and mudler's build pipeline with no cryptographic check
  at install time.

**Follow-ups**

1. **File an upstream issue** asking mudler to sign backend images with
   `--new-bundle-format`, so LocalAI's own verifier can read them. One flag on
   their side; nothing reports it today.
2. **Mirror and re-sign — the durable fix.** Verify upstream's legacy signature
   in CI (cosign reads that format fine; only LocalAI's verifier cannot), copy
   the image **by digest** into `ghcr.io/adorsys-gis`, re-sign with
   `cosign --new-bundle-format` under our GHA keyless identity, and point
   `backendGalleries` at an index we host with `identity_regex` matching our own
   workflow. That restores verification *and* pins the bytes, and is the only
   route to either while upstream signs the way it does. ⚠️ Step one is
   load-bearing: without verifying upstream's signature at mirror time, our
   signature attests only that we copied something.
3. **Re-confirm a real 1024×1024 generation** once the pod is up — still
   outstanding from ADR-0106, and still the ADR-0101 gate.

## Alternatives considered

- **Fix the identity regex.** Rejected: it was never evaluated. The failure is
  upstream of it, and "the regex is wrong" is the wrong lesson to leave behind.
- **Bump LocalAI.** Not available — v4.7.1 is the newest release.
- **Keep verification and leave image generation down.** Defensible, and
  explicitly weighed. Rejected because the fix has no known ETA (it depends on an
  upstream change nobody has requested yet), and the mirror route is days of
  work — an indefinite outage to preserve a control that has never once
  successfully verified anything here.
- **Set `requireBackendIntegrity`.** Would convert this from a crash loop into a
  differently-worded crash loop.
- **Mirror and re-sign now, before restoring service.** The right end state, and
  it is follow-up 2 — but it is new CI, a hosted gallery index and a
  re-run-on-every-bump maintenance burden. Not a hotfix, and the model is down.

## Related

- Supersedes the verification decision of [0105](0105-pin-and-verify-the-localai-backend.md); its other decisions stand
- The fresh volume that exposed it: [0106](0106-restore-the-localai-image-tier.md)
- Original unpinned-backend gap: [0102](0102-localai-instead-of-a-first-party-image-server.md)
- The gate still outstanding: [0101](0101-load-gate-before-federation-no-exceptions.md)
- Charts: `charts/inference/values.yaml` (`defaults.engines.localai`)
