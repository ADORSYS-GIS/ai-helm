# ADR-0103: Own the LocalAI model config instead of naming a gallery entry

**Status:** Accepted
**Date:** 2026-07-28
**Deciders:** @stephane-segning

## Context

[ADR-0102](0102-localai-instead-of-a-first-party-image-server.md) adopted LocalAI
and pointed the catalog entry at a **gallery entry name** (`serving.galleryModel`).
That is the shortest possible configuration — one string — and it was the right
first move. It also hands three decisions to someone else, and once the model ran
we could see what they cost.

**1. The gallery's tuning is for someone else's hardware.** LocalAI's ggml
Z-Image entry ships:

```yaml
step: 25
options:
  - offload_params_to_cpu:true
```

`step: 25` on a model **distilled for 8 steps** is roughly 3× the work for no
quality gain — the entire reason the "Turbo" variant exists.
`offload_params_to_cpu` keeps parameters in host RAM and streams them to the card
over PCIe; measured on our hardware that produced **815 MiB of VRAM used out of
20475**. Both are sensible defaults for a small card and wasteful on a 20 GiB one
holding a ~7 GB quantized model.

**2. A gallery reference is not a content pin.** ADR-0102 recorded this as the
main thing given up in leaving the seed-Job model: a seed Job fetched an exact
commit SHA, so the bytes measured at the load gate were the bytes served. A
gallery entry can be edited upstream.

**3. The gallery name leaks into the gateway.** LocalAI serves a model under the
name of whatever *defines* it, so `modelNameOverride` in `charts/ai-models` has to
track the gallery's capitalisation (`Z-Image-Turbo`) rather than our own naming.
Get it wrong and every gateway request 404s while the model itself is healthy.

Crucially, LocalAI's model-config schema already exposes everything needed to fix
all three — verified in `core/config/model_config.go`: `step`, `cfg_scale`,
`options`, `parameters`, and `download_files` with a **`sha256` per file**.

## Decision

**Supply LocalAI's model configuration ourselves.**

A catalog entry may set `serving.modelConfig` — a YAML block that
`charts/model-server` renders into a ConfigMap and mounts read-only at
`/config`, applied at start-up via `MODELS_CONFIG_FILE`. When it is set,
`MODELS` is deliberately unset: there is no gallery entry left to install.

For `z-image-turbo` the config is the gallery's, with three changes:

| | From | To | Why |
|---|---|---|---|
| `step` | 25 | **8** | The model is distilled for 8; 25 is ~3× the work for nothing |
| `offload_params_to_cpu` | true | **removed** | 815 MiB of a 20475 MiB card was in use; the GPU was idle while the bus worked |
| `sha256` | gallery's | **ours, in git** | Recovers the pinned-bytes guarantee ADR-0102 gave up |

The URIs and checksums are the gallery's, verified against its `index.yaml`. Only
the tuning is ours.

⚠️ **`MODELS_CONFIG_FILE`, not `PRELOAD_MODELS_CONFIG`.** The names read as
synonyms and are not. `PRELOAD_MODELS_CONFIG` is a list of **gallery sources**,
each requiring a `url`; handed raw model configs it tries to fetch `""` and dies
with `unsupported protocol scheme ""` — an error that describes a networking
problem and is really a missing field. `MODELS_CONFIG_FILE` is documented as
"YAML file containing a list of model backend configs", which is what we mount.

The ConfigMap is mounted **outside** the weights volume. `MODELS_PATH` is
writable and LocalAI owns it; a config living there would be contending with the
engine for the same directory.

## Consequences

**Positive**

- Latency and VRAM stop being upstream's choice. The two corrections above are
  pure win on our hardware.
- **The pinned-bytes guarantee is back**, in git, reviewable in a diff — the main
  regression ADR-0102 accepted is substantially undone.
- The model name is ours (`z-image-turbo`), so the gateway override follows our
  naming instead of a third party's capitalisation.
- Adding a second image model is still a values block, not a chart change.

**Negative**

- **We now own tuning we did not write.** When upstream improves the gallery
  entry — a better quant, a fixed option, a new backend — we will not get it for
  free, and nothing tells us it happened. This is the same class of cost as
  owning the server, in much smaller measure, and it is real.
- The config is copied, so it can drift from the gallery's. Anyone changing it
  should diff against `gallery/index.yaml` first.
- One more moving part in the leaf chart (a ConfigMap and a mount).

**Neutral / follow-ups**

- The price must be re-derived: `step: 25 → 8` invalidates the 94.2 s that the
  current figure came from, and the hardware basis is separately wrong (~$234/mo,
  not €184 — needs an ADR superseding [0096](0096-gex44-fleet-cost-recovery-pricing.md)).
- Stale configs from earlier approaches remain on the PVC and are still
  advertised in `/v1/models`. The gateway cannot reach them, but the diffusers
  one is known-broken and should be cleaned.
- This does **not** fix the unpinned, unsigned **backend** (ADR-0102) — that is
  resolved from a `latest` tag at runtime and is a separate problem.

## Alternatives considered

- **Keep the gallery entry and accept its tuning.** Rejected once measured: 3×
  the sampling steps and a GPU sitting idle are not acceptable defaults when the
  fix is a values block.
- **Override just the tuning, keeping the gallery reference.** This is what
  `PRELOAD_MODELS_CONFIG` with `overrides:` would do. Rejected because it keeps
  the unpinned reference — we would still be tracking an entry that can move —
  and because the full config is barely longer than the override.
- **Fork the gallery.** Rejected: all the maintenance of owning the config with
  none of the locality; the config belongs next to the model it configures.
- **Ask upstream to fix `step: 25`.** Worth doing regardless, and does not help
  today. `offload_params_to_cpu` is correct for most of their users; our hardware
  is the unusual case, not theirs.

## Related

- Amends [ADR-0102](0102-localai-instead-of-a-first-party-image-server.md) —
  same engine, we just stop delegating its configuration
- Recovers part of what [ADR-0102](0102-localai-instead-of-a-first-party-image-server.md)
  recorded as given up (pinned bytes)
- Pricing basis: [ADR-0096](0096-gex44-fleet-cost-recovery-pricing.md), which
  needs superseding for an unrelated reason
- Charts: `charts/model-serving/{values.yaml,templates/_helpers.tpl}`,
  `charts/model-server/templates/modelconfig.yaml`
- Session narrative: [`docs/migrations/2026-07-28-image-generation-session-notes.md`](../migrations/2026-07-28-image-generation-session-notes.md)
