# ADR-0105: Pin and verify the LocalAI backend; define the model ourselves

**Status:** Accepted
**Date:** 2026-07-28
**Deciders:** @stephane-segning

## Context

[ADR-0102](0102-localai-instead-of-a-first-party-image-server.md) adopted LocalAI
and recorded two costs it did not solve. Both are now closable, and both were
worse than that ADR realised.

**1. Pinning the server did not pin what runs the model.** We pin
`quay.io/go-skynet/local-ai:v4.7.1-gpu-nvidia-cuda-12` carefully — the CUDA-12 tag
exists specifically to avoid the driver-550 trap. But LocalAI resolves its
inference *backend* separately at runtime, and read from the binary's own
`--help`, **both halves of that float**:

```
--backend-galleries  github:mudler/LocalAI/backend/index.yaml@master
--backend-images-release-tag  latest
```

So the component that answers HTTP was pinned and the component that **executes
the model** was not. Observed live on first boot:

```
installing OCI backend without signature verification
  uri="...local-ai-backends:latest-gpu-nvidia-cuda-12-diffusers"
```

That line contains both problems: `latest`, and no signature check.

**2. Naming a gallery model gave away more than the tuning.** ADR-0103 already
found that the gallery's defaults are for other hardware. Two further
consequences surfaced only once it ran: LocalAI rewrites its own config file on
**every** start (so overwriting it silently discarded our tuning), and the
gallery entry stays advertised in `/v1/models` alongside ours — two image models
where there is one model.

LocalAI turns out to support fixing all of it: `GalleryVerification` is a
keyless-cosign policy per gallery, `download_files` carries a `sha256` per file
in an ordinary model config, and both gallery and image tag are pinnable.

## Decision

**Pin and verify the backend, and define the model entirely ourselves.**

| | Before | After |
|---|---|---|
| Backend gallery | `…/index.yaml@master` | `…/index.yaml@v4.7.1` |
| Backend image tag | `latest` | `v4.7.1` — the server's own release |
| Signature check | none (warning) | keyless cosign: issuer + identity regex + `not_before` |
| Model definition | gallery entry | ours, with `download_files` sha256-pinned |
| `/v1/models` | 2 image models | 1 |

Three things worth stating explicitly:

- **The server and its backend now move together or not at all.** They are pinned
  to the same release, so a backend cannot drift out from under a tested server.
- **`not_before` is the revocation lever.** Keyless cosign certificates are
  ephemeral and there is no CA-side revocation, so advancing that date is the
  only way to invalidate a known compromise window.
- **This restores the pinned-bytes guarantee** ADR-0102 called the main cost of
  adopting LocalAI. `download_files` checksums are in git, reviewable in a diff,
  and the weights are ours again in the sense that matters: the bytes measured at
  the load gate are the bytes served.

`requireBackendIntegrity` is deliberately **left unset**. It rejects any backend
install lacking a verification policy — the correct end state — but it converts a
missing policy anywhere into a hard boot failure, and that deserves one
fresh-volume test rather than a 4am flip. The gallery above is verified either
way; the flag only governs what happens elsewhere.

The chart now **fails the render** when a model sets `modelConfig` without
`galleryModel` and without `backends`. Dropping the gallery model removes the
backend install that came with it as a side effect, and LocalAI reports the
resulting absence as a cooldown cascade that names every backend *except* the
missing one — an error that cost real time to read correctly.

## Consequences

**Positive**

- The supply chain for the image tier is pinned end to end: server, backend
  gallery, backend image, and every weight file by sha256.
- Backends are signature-verified against a named identity, with a revocation
  lever.
- One image model in `/v1/models` instead of two.
- The tuning is durable — nothing rewrites our config, because nothing else
  claims that filename.

**Negative**

- **The cosign identity is unproven here.** The backend is already installed on
  the volume, so verification will not actually be exercised until a fresh
  volume. If the identity regex is wrong, that is when it fails — at the worst
  moment. Mitigation: it is LocalAI's own documented shape for this gallery, and
  reverting is deleting one block.
- **We now track upstream by hand.** Pinning the gallery to `@v4.7.1` means a
  better backend published tomorrow does not arrive, and nothing tells us.
  Bumping the server image now means bumping three pins together.
- **We own the model definition**, including URIs and digests copied from the
  gallery. If upstream fixes an entry, we do not get it for free.

**Neutral / follow-ups**

- Flip `requireBackendIntegrity` after one fresh-volume install confirms the
  policy matches.
- Verify on that same install that `download_files` actually fetches — it is
  first-class in the config schema, but our volume was already populated, so
  this path is untested here.

## Alternatives considered

- **Leave it and document the risk.** Rejected: "the thing that executes the
  model floats and is unsigned" is not a footnote, and it had already been
  carried forward once.
- **Pin without verifying.** Half the problem; a pinned tag still resolves to
  whatever bytes that tag points at.
- **Verify without pinning.** Better than nothing, but a `latest` tag that
  changes under a verified signature is still an untested backend.
- **Set `requireBackendIntegrity` now.** Rejected for tonight — see above. It is
  the intended end state, not a same-session change.

## Related

- Closes the two gaps recorded in [ADR-0102](0102-localai-instead-of-a-first-party-image-server.md)
- Completes [ADR-0103](0103-own-the-localai-model-config.md) — owning the config
  is what makes dropping the gallery install possible
- Charts: `charts/model-serving/{values.yaml,templates/_helpers.tpl}`
