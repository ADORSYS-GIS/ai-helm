# ADR-0109: Ready means *served* — gate the image engine's startup probe on a real generation

**Status:** Accepted
**Date:** 2026-07-29
**Deciders:** @stephane-segning

## Context

[ADR-0100](0100-image-generation-on-the-gpu-fleet.md) listed, among the four
defects that made the first image deployment non-functional:

> The engine loaded **lazily**, on the first request, while `/health` answers 503
> until loaded → deadlock: not-Ready ⇒ no endpoint ⇒ no request ⇒ never loads.

LocalAI does not deadlock — `/readyz` returns 200 regardless — so the defect was
considered solved by the engine swap plus `LOAD_TO_MEMORY`, which LocalAI
documents as *"a list of models to load into memory at startup"*. The chart even
records the intent: *"httpGet on an endpoint that only 200s once loaded."*

**Measured on the fleet, 2026-07-29, `Ready` does not mean loaded.** Immediately
at Ready, with `LOAD_TO_MEMORY=z-image-turbo` set and no watchdog, no request yet
sent:

```
vram=5 MiB  of 20475
root  ./local-ai
root  .../cuda12-stablediffusion-ggml/stablediffusion-ggml --addr …   ← running
```

`/readyz` 200s, the tree is green, the Service has an endpoint — and the card is
empty. The weights arrive on the **first request** and then stay resident
indefinitely.

**This is not an upstream bug, and that matters for the fix.** Read in the
v4.7.1 source, `LOAD_TO_MEMORY` → `PreloadModelByName` → `PreloadModel` →
`ml.Load(...)`, which genuinely spawns the backend and opens the model, returning
an error that would abort startup if it failed. The process listing above
confirms it worked: the `stablediffusion-ggml` backend *is* running at Ready.
What defers is **stable-diffusion.cpp's upload of tensors to the GPU**, which
happens at first inference — one layer *below* LocalAI's abstraction. So no
LocalAI setting reaches it, and there is no configuration fix to prefer.

Ruled out along the way, each checked rather than assumed:

| Hypothesis | Verdict |
|---|---|
| Idle watchdog unloading it | No — `WATCHDOG_IDLE` defaults `false` and is unset |
| `LoadToMemory` skipped via `SingleBackend` | No — the guard is `if LoadToMemory != nil && !SingleBackend`; `SINGLE_ACTIVE_BACKEND` is unset, so preload runs |
| Preload silently no-ops | No — it calls `ml.Load` and the backend process is live at Ready |
| Weights only resident while generating | **No** — disproved: 7985 MiB held flat across 190 s idle |

⚠️ One piece of evidence used early in this investigation was **wrong** and is
recorded here so it isn't repeated: `nvidia-smi` inside the container prints
`No running processes found` even when a process is using the GPU, because it
cannot map PIDs across namespaces. It looked like proof that nothing was running.
Only the reported *memory* figure is trustworthy from inside a container; use
`ps` for processes.

So the cost is small but real, and it lands on a user: the first 1024×1024 after
a pod start took **32.03 s**; warm, the same request takes **29.23 s**.

The wider problem is that **readiness was lying**. An endpoint that promises a
model can serve, while nothing is loaded, is the same class of error ADR-0101 was
written about — a green dashboard is not evidence.

## Decision

**For engines that declare it, the startup probe performs a real inference
request.** The pod gets a Service endpoint only after it has actually served
something.

Expressed as **engine-profile data**, per ADR-0094's contract that engine facts
are data and not `if engine == …` branches:

```yaml
    localai:
      warmup:
        path: /v1/images/generations
        timeoutSeconds: 60
        body: { prompt: warmup, size: 256x256, "n": 1, response_format: b64_json }
```

An engine that omits `warmup` keeps the plain `httpGet` startup probe — `llamacpp`
and `vllm` are unchanged, because their health endpoints already gate on load.

Three details that are load-bearing:

- **256×256, not 1024×1024.** Resolution does not change *which* weights load, so
  the cheapest size that exercises the full path is correct: ~3.8 s, verified to
  take VRAM 5 MiB → 7505 MiB and hold it.
- **The warmup presents the API key**, using the same condition as the `API_KEY`
  env var. Without it every probe 401s and the pod never becomes Ready.
- **The failure path stays cheap.** Before the HTTP server listens — including the
  ~3 minute first-boot backend download — curl fails instantly with
  connection-refused, so the expensive branch only runs once the server is up.

⚠️ `"n": 1` is quoted deliberately. Unquoted `n` is a YAML 1.1 boolean, so `n: 1`
becomes the key `false`; it rendered as `{"false":1,…}` and was caught only by
reading the rendered probe.

⚠️ **This changes the probe's HANDLER TYPE** (`httpGet` → `exec`), and Kubernetes
forbids a probe carrying both. That is safe here only because the orchestrator
syncs its children with **`ServerSideApply=true`**: ArgoCD's field manager owns
`startupProbe` and drops the handler it no longer sets. A client-side
apply/merge against the existing object produces exactly the invalid state —

```
spec.template.spec.containers[0].startupProbe.httpGet:
  Forbidden: may not specify more than 1 handler type
```

— which is what a `kubectl apply --dry-run=server` reported during review before
the cause was understood. If a future chart in this repo ever moves off
ServerSideApply, changing a probe's handler type becomes a delete-and-recreate,
not an edit.

Validation available without deploying, and worth doing for any probe change:
render the **leaf** (not just the orchestrator's child values, which do not show
the final probe), extract the Deployment, rename it, and
`kubectl create --dry-run=server`. That is what confirmed the `exec`-only spec is
schema-valid against the live API.

## Consequences

**Positive**

- No user pays the model-load cost, which is what was asked for.
- Ready now means *this pod has served an image*, the strongest statement a probe
  on this engine can make.
- A model that installs and starts but cannot actually infer now fails at the
  startup gate instead of being advertised — the ADR-0101 discipline moved from a
  human checklist into the deployment.

**Negative**

- One extra generation per pod start (~4 s), and a probe that is more expensive to
  fail than an HTTP GET. Bounded by the connection-refused fast path.
- The probe body is engine-specific config in the profile. That is the intended
  shape, but it does mean adding an image engine means writing its warmup.
- If a future engine's warmup is slow, `timeoutSeconds` needs raising with it;
  the probe timeout is derived as warmup + 10 s.

**Neutral**

- `LOAD_TO_MEMORY` stays set, and stays correct. It does spawn the backend and
  open the model — for a backend that uploads its tensors at load time it would
  be sufficient on its own. It is simply not sufficient for `stablediffusion-ggml`,
  and the values file now says exactly that, so nobody removes it as "the thing
  that didn't work" or trusts it as "the thing that did".
- **Nothing to report upstream here** (unlike ADR-0108). LocalAI's preload does
  what it documents; the deferral belongs to stable-diffusion.cpp. If anything is
  worth raising it is with sd.cpp, and it is not worth raising today.
- ⚠️ **We own this.** The warmup is our Helm, not a LocalAI feature — about
  fifteen lines of template plus a profile block. That is a real, if small,
  maintenance surface, accepted knowingly because the alternative is an endpoint
  that lies and a user who pays for it. It was adopted only after confirming no
  upstream knob exists.

## Alternatives considered

- **Trust `LOAD_TO_MEMORY`.** That is the status quo, and it is measurably wrong.
- **A `postStart` lifecycle hook.** Runs before probes but does not gate the
  endpoint as reliably, and a hanging hook has worse failure modes than a probe
  with a bounded threshold.
- **Point `healthPath` at a "model loaded" endpoint.** There isn't one; `/readyz`
  is the closest and it is exactly what proved insufficient.
- **Accept the ~2.8 s first-request penalty.** Rejected on the explicit
  instruction that the first user should not pay it — and the penalty was never
  the main point. The endpoint being wrong about its own readiness was.

## Related

- Closes the lazy-load defect [0100](0100-image-generation-on-the-gpu-fleet.md) believed fixed
- Same discipline as [0101](0101-load-gate-before-federation-no-exceptions.md): read the numbers, not the dashboard
- Engine-facts-as-data contract from [0094](0094-generic-model-serving-orchestrator.md)
- Found while closing out [0106](0106-restore-the-localai-image-tier.md)/[0108](0108-localai-backend-verification-is-unsatisfiable.md)
- Charts: `charts/inference/{values.yaml,templates/_helpers.tpl}`
