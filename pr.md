## 1. Summary

This PR changes:

- Disables `qwen3-vl-4b-thinking` (vision-language model) on the GPU fleet — frees one card for the replacement
- Adds `qwen3-coder-30b-a3b` — Qwen3-Coder-30B-A3B (MoE 128 experts, 8 active, AWQ INT4) on vLLM — the new coding model
- Enables FP8 KV cache as fleet default (`defaults.kvCacheDtype: fp8_e4m3fn`) for all vLLM models, with per-model override and 5 fail-fast validation guards in `_helpers.tpl` (engine mismatch, invalid value, LMCache+FP8)
- Removes the `qwen3-vl-4b-thinking-local` backend from `charts/ai-models/values.yaml` and sets its model entry to `enabled: false` (gateway off before server off, per `replace-a-model.md`)
- Disables `adorsys-tiny` alias (`enabled: false`) — references the removed backend; would otherwise hard-fail render on merge

It solves:

- Closes #836 — Deploy coding model to GPUs, replacing Qwen-VL

---

## 2. Intent

The intent of this PR is:

> Replace the non-coding-optimized Qwen3-VL-4B-Thinking with a dedicated coding model (Qwen3-Coder-30B-A3B, AWQ INT4) on one fleet GPU, so the platform can serve coding and agentic workloads. The VLM's card is freed and reassigned. FP8 KV cache is enabled fleet-wide as a performance optimization validated in the spike (#839).

---

## 3. Scope

### In Scope

- New model entry `qwen3-coder-30b-a3b` in `charts/inference/values.yaml` (vLLM, AWQ INT4, FP8 KV cache, SHA-pinned at `c58857a7f41c0920f73d1b56678640f9c02017d7`)
- Disable `qwen3-vl-4b-thinking` in `charts/inference/values.yaml` (`enabled: false`)
- Remove `qwen3-vl-4b-thinking-local` backend from `charts/ai-models/values.yaml` and set model entry to `enabled: false`
- Disable `adorsys-tiny` in `charts/ai-models/values.yaml` (`enabled: false`) — references the removed backend
- Fleet default `kvCacheDtype: fp8_e4m3fn` in `defaults:` section of `charts/inference/values.yaml`
- 5 fail-fast validation guards in `charts/inference/templates/_helpers.tpl` (wrong engine, invalid value, LMCache+FP8)
- `--kv-cache-dtype` flag in vLLM engine args, `--cache-type-k/--cache-type-v` in llama.cpp engine args
- CI fixture update in `charts/inference-server/ci/vllm-values.yaml` for `--kv-cache-dtype fp8_e4m3fn`
- Tool call parser set to `qwen3_xml` (not `hermes`) — Qwen3-Coder uses XML function-call format; the model ships its own `qwen3coder_tool_parser.py`

### Out of Scope

- Federating the coding model into the gateway (requires load gate first — ADR-0101)
- Benchmark report on inference-ops (#837)
- SGLang / TensorRT-LLM engine profiles (evaluated in spike #839, deferred)
- HumanEval/MBPP pass-rate measurement (post-merge load gate)
- ADR for FP8 KV cache fleet default (deferred to follow-up — the blast radius is currently 1 model)

---

## 4. Verification

I verified this change by:

- [x] Running automated tests
- [ ] Running manual tests
- [x] Checking logs
- [ ] Checking metrics
- [x] Testing error cases
- [ ] Testing permissions/security behavior
- [ ] Testing rollback or failure behavior, if relevant

Commands run:

```bash
# Lint the inference chart
helm dep build charts/inference
helm lint charts/inference --strict

# Verify render: new model present, old model absent
helm template chk charts/inference | grep -c "qwen3-coder-30b-a3b"
helm template chk charts/inference | grep -c "qwen3-vl-4b-thinking"

# Lint the inference-server leaf chart with CI fixture
helm dep build charts/inference-server
helm lint charts/inference-server -f charts/inference-server/ci/vllm-values.yaml --strict

# Verify catalog consistency (served ↔ federated)
./tools/check-model-catalogs.sh
```

Results:

```text
$ helm lint charts/inference --strict
==> Linting charts/inference
[INFO] Chart.yaml: icon is recommended
1 chart(s) linted, 0 chart(s) failed

$ helm template chk charts/inference | grep -c "qwen3-coder-30b-a3b"
11

$ helm template chk charts/inference | grep -c "qwen3-vl-4b-thinking"
0

$ helm lint charts/inference-server -f charts/inference-server/ci/vllm-values.yaml --strict
1 chart(s) linted, 0 chart(s) failed

$ ./tools/check-model-catalogs.sh
check-model-catalogs: OK (2 served on the GPU fleet, 1 federated cluster-local)
  note: 'qwen3-coder-30b-a3b' is served but not federated — no user can route to it yet.
```

Negative tests (fail-fast guards):

```bash
# Invalid kvCacheDtype value → render fails
helm template chk charts/inference --set models.qwen3-coder-30b-a3b.serving.kvCacheDtype=invalid
# → Error: model qwen3-coder-30b-a3b: serving.kvCacheDtype must be one of [auto fp8 fp8_e5m2 fp8_e4m3fn]

# kvCacheDtype on llama.cpp engine → render fails
# → Error: model ...: serving.kvCacheDtype is a vLLM knob

# kvCacheType on vLLM engine → render fails
# → Error: model ...: serving.kvCacheType is a llama.cpp knob

# LMCache + fp8 → render fails
# → Error: model ...: fp8 KV cache + LMCache is UNVERIFIED on this fleet
```

---

## 5. Screenshots / Evidence

* Rendered engine args for the new model:
  ```
  vllm serve /models/Qwen3-Coder-30B-A3B-Instruct-AWQ \
    --served-model-name qwen3-coder-30b-a3b \
    --max-model-len 8192 --max-num-seqs 2 \
    --gpu-memory-utilization 0.9 \
    --quantization awq --dtype float16 \
    --kv-cache-dtype fp8_e4m3fn \
    --enable-auto-tool-choice --tool-call-parser qwen3_xml
  ```
* Model source: `QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ` @ `c58857a7f41c0920f73d1b56678640f9c02017d7`
* Weights: ~16.8 GB on disk (6 safetensors shards), PVC 35 GiB, seedMaxWorkers 2, seedMemoryLimit 10Gi
* VRAM estimate: `0.9 × 19.99 = 17.99 GiB` budget − 15.66 GiB weights = **~2.33 GiB** for KV cache + CUDA graphs + activations. FP8 KV cache at 8K context = ~0.38 GiB. CUDA graphs capture memory is larger on this 48-layer/128-expert MoE — if vLLM aborts at startup, set `extraArgs: ["--enforce-eager"]`
* Scheduling: `runtimeClassName: nvidia`, `nodeSelector: nvidia.com/gpu.present: "true"`, `nvidia.com/gpu: 1`, `storageClassName: longhorn`, probes on `/health`

---

## 6. Risk Assessment

Risk level:

* [ ] Low
* [x] Medium
* [ ] High

Potential risks:

* **PVC sizing**: 35 GiB for 16.8 GB on disk — staging in `.cache` peaks at ~2× (same mechanism that caused the qwen3-vl-4b-thinking incident #807). Mitigated by sizing at 35 GiB (~2× + margin) and capping seedMaxWorkers at 2
* **MoE architecture on vLLM**: `qwen3_moe` is the first MoE model on this fleet. vLLM supports it natively, but the AWQ Marlin MoE path is unmeasured on this specific card (RTX 4000 SFF Ada)
* **Two lossy layers stacked**: the quant model card warns of significant loss under 4-bit AWQ, and FP8 KV cache adds uncalibrated quantization on top. Both may be fine in practice, but for a model whose value is correctness, the load gate must measure quality, not just speed
* **FP8 KV cache quality**: fleet default `fp8_e4m3fn` is unmeasured on this model — if the quality gate fails, override with `kvCacheDtype: auto` (16-bit) per model
* **CUDA graphs memory**: larger on 48-layer/128-expert MoE than dense models — first failure mode is vLLM aborting at startup with no memory for KV blocks. Mitigation: `extraArgs: ["--enforce-eager"]`
* **VRAM headroom tight**: ~2.33 GiB at `gpuMemoryUtilization: 0.90` — contextSize 8192 is deliberately conservative

Mitigation:

- Conservative contextSize (8192) — raise after load gate measures actual headroom
- `gpuMemoryUtilization: 0.90` with ~2.33 GiB headroom after weights
- SHA-pinned weights (`c58857a7`) — reproducible seed, byte-identical on re-seed
- Rollback = `git revert` the merge commit (weights survive via `reclaimPolicy: Retain` on the Longhorn PV)
- Per-model `kvCacheDtype: auto` exists as instant rollback if FP8 quality fails
- `--enforce-eager` available via `extraArgs` if CUDA graphs exhaust VRAM

---

## 7. AI Usage Declaration

AI was used for:

* [x] Understanding existing code
* [x] Generating code
* [ ] Refactoring
* [ ] Generating tests
* [x] Drafting documentation
* [ ] Reviewing the diff
* [ ] Not used

Human verification:

* [x] I understand every meaningful change in this PR
* [x] I checked generated code manually
* [ ] I checked generated tests manually
* [x] I removed unsupported AI assumptions
* [x] I accept responsibility for this PR

---

## 8. Reviewer Focus

Please focus your review on:

* [x] Correctness — does the model entry produce the right vLLM command?
* [ ] Architecture
* [ ] Security
* [ ] Performance
* [ ] Tests
* [x] Maintainability — is the FP8 KV cache default clearly documented?
* [x] Product intent — does this replace Qwen-VL correctly?
* [x] Edge cases — what happens if the MoE AWQ path fails on this card?
