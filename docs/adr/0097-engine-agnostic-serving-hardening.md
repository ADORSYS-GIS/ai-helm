# ADR-0097: An engine-agnostic hardening baseline for model servers

**Status:** Accepted
**Date:** 2026-07-26
**Deciders:** @stephane-segning

## Context

[ADR-0095](0095-cluster-local-model-federation.md) made self-hosted models
cluster-local and removed their static API key, reasoning that the key existed
only to defend a public endpoint that no longer exists. That reasoning holds — and
the CiliumNetworkPolicy was verified live on 2026-07-26: a pod in the *same*
namespace times out reaching the model, and only `envoy-gateway-system` gets
through.

What that decision did not consider is the engine's **own** default surface.
llama-server announces it at start-up:

```text
W srv llama_server: CORS is set to allow all origins ('*') and no API key is set
W srv llama_server: this can be a security risk (cross-origin attacks)
```

It also serves a full **chat Web UI and static file server on the same port as
the API, enabled by default**. None of that is reachable today, but all of it sits
one mis-edited NetworkPolicy away from being reachable, and none of it is
something a model *backend* needs.

The deeper problem is that this is engine-specific knowledge. llama.cpp's exposure
is a Web UI and a CORS default; vLLM's is different; a future ONNX or TGI runtime
would differ again. Encoding it per model, or per engine at the point of use, means
each new engine silently starts from *its own* defaults rather than from ours.

## Decision

Define the hardening as **fleet policy in `charts/model-serving`
`defaults.security`, stated engine-agnostically**, and map it to per-engine flags
in the orchestrator's `_helpers.tpl`. Every engine we run must end up with:

| Policy | llama.cpp | vLLM |
|---|---|---|
| The engine checks a Bearer itself | `--api-key-file` | `VLLM_API_KEY` |
| No browser UI or static-file surface | `--no-webui` | *n/a — ships no UI* |
| No wildcard CORS | `--cors-origins <gateway origin>` | `--allowed-origins`, **not yet enabled** |

Adding an engine means adding a row to that mapping; the policy statement does not
change. Where an engine satisfies a policy by its own shape rather than by a flag
(vLLM has no Web UI), that is recorded as satisfied, not skipped.

Defaults are **on**, with a **per-model override** (`models.<name>.security`)
rather than fleet-wide opt-in. The asymmetry is deliberate: the API key and the
CORS pin cost nothing operationally, whereas `disableWebUI` is the one knob with
genuine debugging value — and even that costs nothing in the normal path, because
the NetworkPolicy already makes the UI unreachable from any browser. A model being
debugged can flip its own UI back on without weakening the fleet.

Both sides of the key are wired together: the model enforces it, and the
`charts/ai-models` backend presents it via `securityType: APIKey`, reading the
**same** `ssegning-aws` property. They must move in lockstep — a backend that
omits the key gets 401 on every request.

This **amends ADR-0095's "no static API key" default**. ADR-0095's central claim
is unchanged: the NetworkPolicy is the primary control and the key is not what
makes the model safe. The key is defence in depth against that policy being
mis-edited, and it removes an engine warning that would otherwise be normalised.

## Consequences

**Positive**

- A new engine inherits a written policy instead of its own defaults.
- The unauthenticated Web UI and wildcard CORS are gone from the model pods.
- Two independent controls now have to fail before a model is openly reachable.
- The start-up security warning is resolved rather than ignored — warnings that
  are always present stop being read.

**Negative**

- A shared secret now exists in the model pods, which is exactly the rotation and
  leak surface ADR-0095 declined. Accepted knowingly: it is one property, already
  in use, and the NetworkPolicy is still what is actually holding the line.
- The model and its gateway backend must stay in lockstep; getting one side wrong
  produces a uniform 401 that looks like a model fault.
- `kubectl port-forward` debugging now needs the key from the Secret, and the Web
  UI needs a per-model override.

**Neutral / follow-ups**

- ⚠️ **vLLM's `--allowed-origins` is specified but NOT enabled**, because it has
  not been verified against a running vLLM pod on this fleet and a bad flag
  crash-loops the engine. Verify at the Qwen3-8B-AWQ load gate, then promote it to
  a fleet default.
- The key reuses the long-standing `vllm_local_api_key` property, proven to
  resolve. A dedicated fleet property would be cleaner but must exist in AWS
  Secrets Manager *before* any model points at it — the binding is
  `optional: false`, so a missing property blocks the pod in `ContainerCreating`.
- Separately fixed alongside this: OpenMythos's thinking default moved from
  `--chat-template-kwargs '{"enable_thinking": false}'` to `--reasoning off`, the
  supported flag; llama-server logs the former as deprecated at start-up.

## Alternatives considered

- **Leave it as ADR-0095 decided** — rejected once the engine's own surface was
  read rather than assumed. "Unreachable today" is a statement about one
  NetworkPolicy, and the Web UI is not something a backend should ever serve.
- **Opt-in hardening per model** — rejected. Security defaults that must be
  remembered are the ones that get forgotten, and the cost here is close to zero.
  Per-model opt-*out* gives the same escape hatch with a safer default.
- **Hardening flags written per model in the catalog** — rejected: it puts
  security decisions in the file juniors edit most, where they would be copied
  between models and drift.
- **A proxy sidecar enforcing auth uniformly** — rejected, and worth stating
  because it is the historical answer here. Both engines authenticate natively;
  the Caddy sidecar in the legacy charts was only ever needed for
  `kserve/huggingfaceserver`, which ignores `VLLM_API_KEY` (ADR-0022) and is
  deliberately not an engine profile.

## Related

- Amends [ADR-0095](0095-cluster-local-model-federation.md) (the API-key default)
- [ADR-0094](0094-generic-model-serving-orchestrator.md) — where the policy lives
- Charts: `charts/model-serving/values.yaml` (`defaults.security`),
  `charts/model-serving/templates/_helpers.tpl`, `charts/ai-models/values.yaml`
