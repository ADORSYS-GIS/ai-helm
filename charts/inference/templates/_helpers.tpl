{{/*
═══════════════════════════════════════════════════════════════════════════════
 inference helpers — the ENGINE PROFILES.

 This file is the machinery that lets a ~15-line catalog entry become a complete
 model deployment. It expands one `models:` entry into the full values block the
 `inference-server` leaf (and its bjw-template subchart) needs.

 Why here and not in the leaf: a Helm parent cannot compute SUBCHART values at
 render time. The old per-model charts hit that wall and worked around it by
 hardcoding the seed repo/glob in the bjw values with a "⚠️ keep in sync with
 model.hfRepo" comment — a standing invitation to ship a model that serves one
 set of weights and downloads another. The orchestrator has no such limit: it
 writes each child's values as a YAML string, so every derived value is computed
 exactly once, from one source of truth.

 Adding an engine = adding a profile here + a `ci/<engine>-values.yaml` fixture
 in charts/inference-server. Nothing else in the repo changes.
═══════════════════════════════════════════════════════════════════════════════
*/}}

{{/*
inference.argocd.destinationClusterRef

Emits the ArgoCD destination cluster identity line and HARD-FAILS if it resolves
to the in-cluster API server without an explicit opt-in. Enforces ADR-0017: the
workloads this repo generates target home-remote, never the cluster ArgoCD runs
in. Identical contract to `ai-models.argocd.destinationClusterRef`.

⚠️ Note the two-tier split: the ApplicationSet itself is a CONTROL object and
lands in-cluster/argocd (via the charts/apps `controlPlane: true` entry); the
CHILD Applications it generates are workloads and come through this guard.
*/}}
{{- define "inference.argocd.destinationClusterRef" -}}
{{- $d := . | default dict -}}
{{- $name := $d.name | default "" -}}
{{- $server := $d.server | default "" -}}
{{- $allow := $d.allowInCluster | default false -}}
{{- $inClusterServers := list "https://kubernetes.default.svc" "https://kubernetes.default.svc:443" -}}
{{- $isInCluster := or (eq $name "in-cluster") (has $server $inClusterServers) -}}
{{- if and $isInCluster (not $allow) -}}
{{- fail (printf "\n\n  REFUSING TO RENDER: ArgoCD destination resolved to the in-cluster API\n  (name=%q server=%q).\n\n  Model workloads must target the home-remote cluster (where the GPU nodes are),\n  never the cluster ArgoCD runs in. Either:\n    - set argocd.destination.name to the remote context (default \"home-remote\"), or\n    - if you REALLY mean in-cluster, set argocd.destination.allowInCluster: true.\n\n  See ADR-0017 and ADR-0095.\n" $name $server) -}}
{{- end -}}
{{- if $server -}}
server: {{ $server | quote }}
{{- else -}}
name: {{ $name | default "home-remote" | quote }}
{{- end -}}
{{- end -}}


{{/*
inference.storagePath — the sub-directory of the weights volume for a model.
Defaults to the HF repo's last path segment, so `jabbatheduck/OpenMythos-GGUF`
becomes `OpenMythos-GGUF`. Overridable per model.
Input: the model's `weights` dict.
*/}}
{{- define "inference.storagePath" -}}
{{- .storagePath | default (last (splitList "/" (required "weights.hfRepo is required" .hfRepo))) -}}
{{- end -}}


{{/*
inference.seedScript — the weight-download script for the seed Job.

Two shapes, one per engine family:
  llamacpp → fetch the ONE matching GGUF and symlink it to a stable
             `model.gguf`, so the server args never mention a filename that
             changes when the quant is re-uploaded.
  vllm     → fetch the whole safetensors repo.

Both pin an HF `--revision` (a commit SHA, never a branch) and write a `.seeded`
stamp holding revision+selector. The Job is an ArgoCD Sync hook, so it runs on
EVERY sync; the stamp turns the 2nd..Nth run into a no-op instead of a multi-GB
re-verification against the Hub. Change the revision or the include glob and the
stamp no longer matches, so the weights re-seed — which is exactly what
"replace the model" should mean.

Input: dict "weights" <weights> "dir" <modelDir>
*/}}
{{- define "inference.seedScript" -}}
{{- $w := .weights -}}
{{- $dir := .dir -}}
{{- $rev := $w.revision | default "main" -}}
{{- $include := $w.include | default "" -}}
{{- /* `hf download` fans out over EIGHT workers by default, and hf_xet buffers
       per file. On a repo whose shards are ~10 GB each that is what decides
       whether the Job fits in its memory limit — not the total repo size. Cap it
       for big-shard repos; see `weights.seedMaxWorkers`. */ -}}
{{- $workers := $w.seedMaxWorkers | default 0 -}}
MODEL_DIR="{{ $dir }}"
STAMP="{{ $rev }}|{{ $include }}"
mkdir -p "$MODEL_DIR"
if [ -f "$MODEL_DIR/.seeded" ] && [ "$(cat "$MODEL_DIR/.seeded")" = "$STAMP" ]; then
  echo "Weights already seeded ($STAMP) — nothing to do."
  exit 0
fi
echo "Seeding {{ $w.hfRepo }} @ {{ $rev }}{{ if $include }} (include: {{ $include }}){{ end }} -> $MODEL_DIR"
pip install --no-cache-dir -q --root-user-action=ignore "huggingface_hub[hf_xet]>=1.0"
{{- if $include }}
hf download {{ $w.hfRepo }} --revision {{ $rev }} --include {{ $include | quote }} --local-dir "$MODEL_DIR"
GGUF="$(find "$MODEL_DIR" -maxdepth 2 -name '*.gguf' -size +1M | head -1)"
if [ -z "$GGUF" ]; then echo "FATAL: no .gguf matched {{ $include }}"; exit 1; fi
ln -sf "$GGUF" "$MODEL_DIR/model.gguf"
echo "Linked $GGUF -> $MODEL_DIR/model.gguf"
{{- else }}
hf download {{ $w.hfRepo }} --revision {{ $rev }}{{ if $workers }} --max-workers {{ $workers }}{{ end }} --local-dir "$MODEL_DIR"
{{- end }}
printf '%s' "$STAMP" > "$MODEL_DIR/.seeded"
# ⚠️ Reclaim the staging area. `hf download --local-dir` writes the whole repo
# into <dir>/.cache/huggingface first and then materialises the real files, so
# PEAK disk is roughly TWICE the repo size — and the staging copy is kept
# afterwards, doubling the volume forever. Removing it only after the stamp is
# written keeps a failed or interrupted run resumable (which matters at 33 GB)
# while making the steady state just the weights.
rm -rf "$MODEL_DIR/.cache"
echo "Seed complete."
{{- end -}}


{{/*
inference.serverArgs — the engine command line.

llama.cpp: the image's entrypoint IS llama-server, so these are bare flags.
  -ngl 99 offloads every layer to the GPU; --jinja enables tool calling via the
  model's own chat template; --metrics exposes the Prometheus endpoint the
  ServiceMonitor scrapes. NO --api-key-file: the model is cluster-local and the
  NetworkPolicy is the control (ADR-0095).

vLLM: `lmcache/vllm-openai` is the LMCache-paired build of the OpenAI server —
  the combination this repo has actually run (charts/model-serving-qwen25-3b-awq).
  LMCache is opt-in per model and offloads KV to host RAM for prefix reuse.
  NOTE: --enforce-eager is NOT set by default any more. It was a VRAM-saving
  measure on the 12 GB A2000; on a 20 GiB Ada card CUDA graphs are affordable
  and materially faster. Add it via extraArgs if a model is tight on VRAM.

localai: LocalAI (ADR-0102) is configured ENTIRELY BY ENVIRONMENT, not by flags —
  which model to serve, where to keep weights and backends, and the API key all
  arrive as env vars (see childValues). It therefore contributes no args at all,
  and `extraArgs` remains available for the rare case.

Input: dict "name" <name> "engine" <engine> "serving" <serving> "dir" <modelDir> "lmcache" <lmcache>
Output: a YAML list of strings.
*/}}
{{- define "inference.serverArgs" -}}
{{- $name := .name -}}
{{- $s := .serving | default dict -}}
{{- $dir := .dir -}}
{{- $apiKey := .apiKey -}}
{{- $sec := .security | default dict -}}
{{- $args := list -}}
{{- if eq .engine "llamacpp" -}}
  {{- $args = concat $args (list
      "--model" (printf "%s/model.gguf" $dir)
      "--alias" $name
      "--host" "0.0.0.0"
      "--port" "8080"
      "-ngl" (toString (default 99 $s.gpuLayers))
      "--ctx-size" (toString (required "serving.contextSize is required" $s.contextSize))
      "--parallel" (toString (default 4 $s.parallel))
      "--metrics") -}}
  {{- with $s.kvCacheType -}}
    {{- /* KV-cache precision (llama.cpp --cache-type-k/--cache-type-v). Default
           is f16; q8_0 is the usual first step (~half the KV memory, minimal
           quality loss), the aggressive end is q4_0. Applies the SAME type to
           both K and V — llama.cpp lets you mix them, but there is no measured
           case for it on this fleet, and a single knob keeps the catalog
           honest. Value is validated against llama.cpp's accepted set in
           childValues. */ -}}
    {{- $args = concat $args (list "--cache-type-k" . "--cache-type-v" .) -}}
  {{- end -}}
  {{- if ne (default true $s.jinja) false -}}
    {{- $args = append $args "--jinja" -}}
  {{- end -}}
  {{- /* Thinking default. `--reasoning on|off|auto` is the supported flag;
         setting `enable_thinking` through --chat-template-kwargs still works but
         llama-server logs it as DEPRECATED at start-up. */ -}}
  {{- with $s.reasoning -}}
    {{- $args = concat $args (list "--reasoning" .) -}}
  {{- end -}}
  {{- /* ── Hardening (ADR-0097). llama-server enforces the Bearer itself, from a
         FILE — no sidecar, ever. The Web UI and the '*' CORS default are the two
         surfaces its own start-up warning complains about. */ -}}
  {{- if $apiKey -}}
    {{- $args = concat $args (list "--api-key-file" (printf "%s/api_key" (.apiKeyPath | default "/etc/model-api-key"))) -}}
  {{- end -}}
  {{- if ne (default true $sec.disableWebUI) false -}}
    {{- $args = append $args "--no-webui" -}}
  {{- end -}}
  {{- with $sec.corsOrigins -}}
    {{- $args = concat $args (list "--cors-origins" .) -}}
  {{- end -}}
{{- else if eq .engine "vllm" -}}
  {{- /* ⚠️ The model path is a POSITIONAL argument and must come FIRST. The
         image's entrypoint is `vllm serve`, whose parser declares `model_tag`
         positionally: passing it as `--model` fails at start-up with
         "error: the following arguments are required: model_tag" and
         crash-loops the pod. This matches the shape the legacy vLLM charts
         actually ran with (`/mnt/models` as arg 0). */ -}}
  {{- $args = concat $args (list
      $dir
      "--served-model-name" $name
      "--host" "0.0.0.0"
      "--port" "8080"
      "--max-model-len" (toString (required "serving.contextSize is required" $s.contextSize))
      "--max-num-seqs" (toString (default 4 $s.parallel))
      "--gpu-memory-utilization" (toString (default 0.90 $s.gpuMemoryUtilization))) -}}
  {{- with $s.quantization -}}
    {{- $args = concat $args (list "--quantization" .) -}}
  {{- end -}}
  {{- with $s.dtype -}}
    {{- $args = concat $args (list "--dtype" .) -}}
  {{- end -}}
  {{- with $.kvCacheDtype -}}
    {{- /* KV-cache precision (--kv-cache-dtype). The EFFECTIVE value: fleet
           default `defaults.kvCacheDtype` (fp8_e4m3fn) unless the catalog
           entry overrides it with `serving.kvCacheDtype`. fp8_e5m2 /
           fp8_e4m3fn store 8-bit values with a per-tensor scale, halving the
           KV footprint at a measured quality cost — nothing else changes:
           weights and activations stay in `--dtype`. `auto` = 16-bit, the
           pre-quantization behaviour. Validated against vLLM's accepted set
           in childValues before we get here; passed through verbatim. */ -}}
    {{- $args = concat $args (list "--kv-cache-dtype" .) -}}
  {{- end -}}
  {{- with $s.toolCallParser -}}
    {{- $args = concat $args (list "--enable-auto-tool-choice" "--tool-call-parser" .) -}}
  {{- end -}}
  {{- if .lmcache -}}
    {{- $args = concat $args (list "--kv-transfer-config" "{\"kv_connector\":\"LMCacheConnectorV1\",\"kv_role\":\"kv_both\"}") -}}
  {{- end -}}
  {{- /* Hardening (ADR-0097). vLLM ships NO browser UI, so disableWebUI is a
         no-op here — the policy is satisfied by the engine's own shape rather
         than by a flag, which is the point of expressing it engine-agnostically.
         The API key arrives as VLLM_API_KEY (see childValues), enforced natively
         by vLLM's own OpenAI server — this is NOT kserve/huggingfaceserver, which
         ignores it and is deliberately not an engine profile (ADR-0022).
         CORS: vLLM defaults `--allowed-origins` to ['*'], exactly like llama.cpp,
         so the same fleet policy applies. ⚠️ The flag is typed `json.loads`, so
         the value MUST be a JSON array — a bare `https://host` is rejected by the
         parser and crash-loops the pod. Verified against the live v0.25.1 parser:
             --allowed-origins '["https://api.ai.camer.digital"]'  -> accepted
             --allowed-origins 'https://api.ai.camer.digital'      -> REJECTED
         `toJson (list ...)` produces the array form. */ -}}
  {{- with $sec.corsOrigins -}}
    {{- $args = concat $args (list "--allowed-origins" (toJson (list .))) -}}
  {{- end -}}
  {{- /* Thinking default — the same POLICY as the llama.cpp `--reasoning` flag,
         expressed with vLLM's equivalent. Qwen3 reasons by default, and vLLM
         emits the trace as raw `<think>` tags INSIDE `content` unless a
         `--reasoning-parser` is configured, so a federated model returns visible
         markup to users. `--default-chat-template-kwargs` is typed json.loads.
         With `reasoning: on`, set `serving.reasoningParser` too (e.g. `qwen3`) or
         the trace lands in content rather than `reasoning_content`. */ -}}
  {{- if $s.reasoning -}}
    {{- if eq (toString $s.reasoning) "off" -}}
      {{- $args = concat $args (list "--default-chat-template-kwargs" "{\"enable_thinking\": false}") -}}
    {{- else if eq (toString $s.reasoning) "on" -}}
      {{- $args = concat $args (list "--default-chat-template-kwargs" "{\"enable_thinking\": true}") -}}
      {{- with $s.reasoningParser -}}
        {{- $args = concat $args (list "--reasoning-parser" .) -}}
      {{- end -}}
    {{- end -}}
  {{- end -}}
{{- else if eq .engine "localai" -}}
  {{- /* Nothing. LocalAI is env-configured (MODELS / MODELS_PATH / BACKENDS_PATH
         / API_KEY), and its entrypoint already starts the server. Passing flags
         here would only override that. */ -}}
{{- end -}}
{{- $args = concat $args (default (list) $s.extraArgs) -}}
{{- range $args }}
- {{ . | quote }}
{{- end }}
{{- end -}}


{{/*
inference.childValues — the whole values block for one inference-server child.

Input: dict "root" $ "name" <modelName> "cfg" <modelConfig>
Output: YAML (unindented; the caller indents it into the ApplicationSet element).
*/}}
{{- define "inference.childValues" -}}
{{- $root := .root -}}
{{- $name := .name -}}
{{- $cfg := .cfg -}}
{{- $d := $root.Values.defaults -}}
{{- $engine := required (printf "model %s: `engine` is required (llamacpp|vllm|localai)" $name) $cfg.engine -}}
{{- if not (has $engine (list "llamacpp" "vllm" "localai")) -}}
{{- fail (printf "model %s: unknown engine %q — expected llamacpp, vllm or localai. Add a profile in charts/inference/templates/_helpers.tpl if you mean to introduce one." $name $engine) -}}
{{- end -}}
{{- $eng := index $d.engines $engine -}}
{{- /* Per-model image override, merged key-by-key over the engine profile's.
       Lets a catalog entry pin a digest once the model is load-gated, or run a
       one-off build, without forking the profile for every other model on it. */ -}}
{{- $image := merge (deepCopy ($cfg.image | default dict)) (deepCopy $eng.image) -}}
{{- /* Does this engine fetch its own weights? LocalAI pulls both the model and
       its inference backend from its galleries at start-up, so there is no seed
       Job, no HF token, and the volume must be writable. The two text engines
       are the other way round: a seed Job pre-places the weights and the model
       mounts them read-only. */ -}}
{{- /* ⚠️ `hasKey`, NOT `default true $eng.seedJob` — `default` treats `false` as
       empty and hands back `true`, so a profile that opts OUT would still get a
       seed Job. Same trap as `metrics` below; it is easy to write and silent to
       get wrong. */ -}}
{{- $seed := not (and (hasKey $eng "seedJob") (not $eng.seedJob)) -}}
{{- /* Defining the model ourselves removes the gallery install, and with it the
       BACKEND install it performed as a side effect. Fail at render rather than
       let LocalAI discover it at boot, where a missing backend surfaces as a
       cooldown cascade that names every backend except the one that is absent. */ -}}
{{- if and (eq $engine "localai") ($cfg.serving).modelConfig (not ($cfg.serving).galleryModel) -}}
{{- if not ($cfg.serving).backends -}}
{{- fail (printf "model %s: serving.backends is required when serving.modelConfig is set without serving.galleryModel — nothing else installs the inference backend" $name) -}}
{{- end -}}
{{- end -}}
{{- $w := $cfg.weights | default dict -}}
{{- if and $seed (not $cfg.weights) -}}
{{- fail (printf "model %s: `weights` is required for engine %s (it is seeded by a Job; only self-downloading engines may omit it)" $name $engine) -}}
{{- end -}}
{{- $s := $cfg.serving | default dict -}}
{{- /* ── KV-cache precision ──────────────────────────────────────────────────
       FLEET DEFAULT: `defaults.kvCacheDtype` (fp8_e4m3fn) applies to EVERY
       vLLM model unless the catalog entry overrides it with its own
       `serving.kvCacheDtype`. A per-model `auto` (back to 16-bit) is how one
       model opts out without a fleet-wide policy change.
       llama.cpp has NO fp8 vocabulary (its 8-bit cache type is q8_0, an int8
       block quant), so its per-model `serving.kvCacheType` stays explicit —
       there is no fleet default to inherit, and `defaults.kvCacheDtype` is
       vLLM-only. LocalAI's diffusion backend has no KV cache to quantize.
       Fail-fast: a per-model knob on the wrong engine, or a value the engine
       does not accept, fails the render rather than dropping on the floor. */ -}}
{{- $kvCacheDtype := $s.kvCacheDtype | default $d.kvCacheDtype -}}
{{- if and $s.kvCacheDtype (ne $engine "vllm") -}}
{{- fail (printf "model %s: serving.kvCacheDtype (%q) is a vLLM knob — llama.cpp models use serving.kvCacheType, LocalAI has no KV cache to quantize" $name $s.kvCacheDtype) -}}
{{- end -}}
{{- if and (eq $engine "vllm") $kvCacheDtype (not (has $kvCacheDtype (list "auto" "fp8" "fp8_e5m2" "fp8_e4m3fn"))) -}}
{{- fail (printf "model %s: serving.kvCacheDtype must be one of [auto fp8 fp8_e5m2 fp8_e4m3fn], got %q — it is passed verbatim to --kv-cache-dtype, so it must be a value vLLM accepts" $name $kvCacheDtype) -}}
{{- end -}}
{{- if and $s.kvCacheType (ne $engine "llamacpp") -}}
{{- fail (printf "model %s: serving.kvCacheType (%q) is a llama.cpp knob — vLLM models use serving.kvCacheDtype, LocalAI has no KV cache to quantize" $name $s.kvCacheType) -}}
{{- end -}}
{{- if and $s.kvCacheType (not (has $s.kvCacheType (list "f32" "f16" "bf16" "q8_0" "q4_0" "q4_1" "q5_0" "q5_1" "q6_K" "iq1_s" "iq2_s" "iq2_xs" "iq2_xxs" "iq3_s" "iq3_xs" "iq3_xxs" "iq4_nl" "iq4_xs"))) -}}
{{- fail (printf "model %s: serving.kvCacheType must be one of llama.cpp's --cache-type-k/--cache-type-v values (f32 f16 bf16 q8_0 q4_0 q4_1 q5_0 q5_1 q6_K iq1_s iq2_s iq2_xs iq2_xxs iq3_s iq3_xs iq3_xxs iq4_nl iq4_xs), got %q" $name $s.kvCacheType) -}}
{{- end -}}
{{- $res := $cfg.resources | default dict -}}
{{- $gpu := $d.gpu -}}
{{- /* Self-downloading engines have no HF repo to derive a directory from, so
       the model name is the storage path — it is already unique per model. */ -}}
{{- /* ⚠️ NOT `ternary`: it evaluates BOTH arms eagerly, so the seeded branch's
       `required "weights.hfRepo is required"` fires even for an engine that has
       no HF repo at all. */ -}}
{{- $storagePath := "" -}}
{{- if $seed -}}
{{- $storagePath = include "inference.storagePath" $w -}}
{{- else -}}
{{- $storagePath = $w.storagePath | default $name -}}
{{- end -}}
{{- $dir := printf "/models/%s" $storagePath -}}
{{- $lmcache := and (eq $engine "vllm") (default false ($cfg.lmcache | default dict).enabled) -}}
{{- $pvcName := printf "%s-weights" $name -}}
{{- /*
Optional engine-enforced API key. OFF unless a catalog entry opts in — under
ADR-0095 a model is cluster-local and the CiliumNetworkPolicy is the control, so
there is normally no key to present.

When it IS on, BOTH engines enforce it natively and NEITHER gets a proxy sidecar:
llama-server reads it from a file (`--api-key-file`), vLLM's own OpenAI server
reads `VLLM_API_KEY` from the environment. The Caddy auth-proxy the legacy charts
carried was never about vLLM — it was needed only for `kserve/huggingfaceserver`,
KServe's wrapper, which IGNORES `VLLM_API_KEY` (ADR-0022 verified: unauthenticated
and wrong-key both returned 200). That wrapper is not an engine option here, so
the sidecar has nothing to come back for.
*/ -}}
{{- /* Fleet security policy (ADR-0097), with a per-model override so one model
       can relax a knob — in practice `disableWebUI: false` while debugging —
       without weakening the fleet. Per-model wins key-by-key. */ -}}
{{- $sec := merge (deepCopy ($cfg.security | default dict)) (deepCopy ($d.security | default dict)) -}}
{{- $ak := merge (deepCopy ($cfg.apiKey | default dict)) (deepCopy ($sec.apiKey | default dict)) -}}
{{- $apiKey := default false $ak.enabled -}}
{{- $apiKeySecret := printf "%s-api-key" $name -}}
{{- /* HOW this engine takes the key — a property of the engine, not of the
       model. `file` mounts the Secret and the args point at it (llama.cpp);
       `env` passes it as a named variable (vLLM, zimage). Expressed as profile
       data so a new engine does not add another `eq $engine "..."` branch. */ -}}
{{- $akMode := ($eng.apiKey | default dict).mode | default "file" -}}
{{- if and $apiKey (not (has $akMode (list "file" "env"))) -}}
{{- fail (printf "engine %s: apiKey.mode must be file or env, got %q" $engine $akMode) -}}
{{- end -}}
{{- $akEnvName := ($eng.apiKey | default dict).envName -}}
{{- if and $apiKey (eq $akMode "env") (not $akEnvName) -}}
{{- fail (printf "engine %s: apiKey.envName is required when apiKey.mode is env" $engine) -}}
{{- end -}}
{{- $akPath := ($eng.apiKey | default dict).path | default "/etc/model-api-key" -}}
model:
  name: {{ $name | quote }}
  engine: {{ $engine | quote }}
  storagePath: {{ $storagePath | quote }}

pvc:
  enabled: true
  name: {{ $pvcName | quote }}
  storageClassName: {{ $d.storageClassName | quote }}
  accessMode: ReadWriteMany
  size: {{ printf "%dGi" (int (required (printf "model %s: weights.sizeGi is required" $name) $w.sizeGi)) | quote }}

hfToken:
{{- if $seed }}
{{- toYaml $d.hfToken | nindent 2 }}
{{- else }}
  # No seed Job for this engine — it downloads its own weights, so there is no
  # Hub pull of ours to authenticate.
  enabled: false
{{- end }}

apiKey:
  enabled: {{ $apiKey }}
{{- if $apiKey }}
  secretName: {{ $apiKeySecret | quote }}
  dataKey: api_key
  externalSecret:
    enabled: true
    secretStore: {{ $ak.secretStore | default "ssegning-aws" | quote }}
    refreshInterval: 1h
    key: {{ $ak.key | default "ai/camer/digital/prod/env" | quote }}
    property: {{ required (printf "model %s: apiKey.property is required when apiKey.enabled" $name) $ak.property | quote }}
{{- end }}

{{- with $s.modelConfig }}
# Our own LocalAI model config (ADR-0103): our tuning, our pinned checksums.
modelConfig: |
{{- . | nindent 2 }}
{{- end }}

networkPolicy:
{{- toYaml $d.networkPolicy | nindent 2 }}

{{/* An engine profile may declare `metrics: false` when the server exposes no
     Prometheus endpoint at all (zimage). Scraping it anyway would poll a 404
     every 30s forever and put a permanently-down target in Mimir, which is worse
     than no target: it trains people to ignore a red panel. Expressed on the
     engine rather than per model because it is a property of the server, and
     `hasKey` rather than `default` because `default true false` is true — the
     classic Helm boolean trap. */}}
serviceMonitor:
{{- if and (hasKey $eng "metrics") (not $eng.metrics) }}
  enabled: false
{{- else }}
{{- toYaml $d.serviceMonitor | nindent 2 }}
{{- end }}

# ── bjw-template: the workload ────────────────────────────────────────────────
modelServing:
  global:
    fullnameOverride: {{ $name | quote }}

  defaultPodOptions:
    # GPU scheduling is expressed as a RESOURCE REQUEST (see the model container
    # below), not a hand-assignment to a named node: the scheduler picks a GPU
    # node with a free card. With N GPUs, the N+1st enabled model simply sits
    # Pending with `Insufficient nvidia.com/gpu` — a legible queue instead of the
    # manual "disable that model to enable this one" dance the old charts needed.
    #
    # The nodeSelector/toleration are still required, and they apply to the SEED
    # Job too — not for the GPU, but because Longhorn only runs on the GPU nodes
    # (ADR-0092), so a pod elsewhere could not mount the weights volume at all.
    runtimeClassName: {{ $gpu.runtimeClassName | quote }}
    nodeSelector:
      {{- toYaml $gpu.nodeSelector | nindent 6 }}
    tolerations:
      {{- toYaml $gpu.tolerations | nindent 6 }}
    labels:
      # Selector for the CiliumNetworkPolicy, the ServiceMonitor and the Service.
      ai-helm.adorsys-gis.github.io/model: {{ $name | quote }}

  controllers:
    # ── The model server ─────────────────────────────────────────────────────
    main:
      # Deployment + `Recreate`, NOT a StatefulSet (ADR-0098, amending ADR-0030).
      #
      # `Recreate` is required, not cosmetic: it terminates the old pod fully
      # before creating the new one, so two pods never contend for the single
      # `nvidia.com/gpu: 1`. Under RollingUpdate with any surge the new pod would
      # sit Pending forever waiting for a card the old pod still holds, while the
      # old pod waits for the new one to be Ready — a deadlock.
      #
      # Why not a StatefulSet: it gave the same single-instance guarantee but
      # defaults to `podManagementPolicy: OrderedReady`, under which the
      # controller refuses to replace a pod that is not Ready. A CRASH-LOOPING
      # POD THEREFORE BLOCKS ITS OWN FIX — the corrected chart merges and syncs,
      # `.spec.template` holds the new args, and the pod keeps running the old
      # ones indefinitely (currentRevision != updateRevision) until somebody runs
      # `kubectl delete pod`. This is documented Kubernetes behaviour, not a bug:
      # see the StatefulSet "Forced rollback" docs. A Deployment has no such
      # gate — it deletes the old pod and moves on, so a bad config self-heals on
      # the next merge.
      #
      # We use no StatefulSet-only feature: no volumeClaimTemplates (the weights
      # PVC is our own RWX claim, mounted by existingClaim), no ordinal identity,
      # no stable network name. So the gate bought us nothing and cost us a
      # manual step during exactly the incidents where it hurts most.
      type: deployment
      strategy: Recreate
      # One model, one GPU, always on. A deploy is ~1–2 min of downtime while the
      # replacement loads its weights; single GPU means no HA by construction.
      replicas: 1
      annotations:
        argocd.argoproj.io/sync-wave: "1"
      pod:
        securityContext:
          {{- toYaml $eng.podSecurityContext | nindent 10 }}
      {{- if $s.modelConfig }}
      initContainers:
        # ⚠️ Install our model config INTO MODELS_PATH — the only place LocalAI
        # was ever reading one from.
        #
        # We first tried to inject it via MODELS_CONFIG_FILE and the engine
        # loaded the model NAME but not `parameters.model`, handing the backend a
        # model id where it expected a weights file. Inspecting the volume showed
        # why: a gallery install writes a plain `<name>.yaml` into MODELS_PATH,
        # and that file — 249 bytes — is what actually drives the backend. So we
        # write the same file, with our tuning instead of the gallery's.
        #
        # Runs before the engine, and overwrites deliberately: the gallery marker
        # (`._gallery_<name>.yaml`) makes LocalAI skip re-installing an entry it
        # has already installed, so our version survives start-up.
        model-config:
          image:
            repository: busybox
            tag: "1.36"
            pullPolicy: IfNotPresent
          command: ["/bin/sh", "-ec"]
          args:
            - |
              DEST="{{ $dir }}/models/{{ $s.modelConfigFile | default (printf "%s.yaml" $name) }}"
              mkdir -p "$(dirname "$DEST")"
              cp /config/models.yaml "$DEST"
              echo "installed model config -> $DEST"
              cat "$DEST"
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop:
                - ALL
            runAsNonRoot: false
            runAsUser: 0
            seccompProfile:
              type: RuntimeDefault
          resources:
            requests: { cpu: "50m", memory: 32Mi }
            limits:   { cpu: "200m", memory: 64Mi }
      {{- end }}
      containers:
        model:
          image:
            repository: {{ $image.repository | quote }}
            tag: {{ $image.tag | quote }}
            pullPolicy: {{ $image.pullPolicy | default "IfNotPresent" | quote }}
          {{- /* Omit the key entirely when an engine contributes no args (LocalAI
                 is env-configured). An empty `args:` is YAML null, which bjw
                 still renders — blanking the image's own command. */ -}}
          {{- $serverArgs := include "inference.serverArgs" (dict "name" $name "engine" $engine "serving" $s "dir" $dir "lmcache" $lmcache "apiKey" $apiKey "security" $sec "apiKeyPath" $akPath "kvCacheDtype" $kvCacheDtype) | trim }}
          {{- with $serverArgs }}
          args:
            {{- . | nindent 12 }}
          {{- end }}
          {{- if or $lmcache (and $apiKey (eq $akMode "env")) (eq $engine "localai") }}
          env:
            {{- if eq $engine "localai" }}
            # LocalAI is configured entirely by environment (ADR-0102).
            #
            # MODELS is the gallery entry to install and serve at start-up. ⚠️ The
            # exact accepted form for a gallery reference is the FIRST thing the
            # load gate must confirm — it is read by InstallModels(... models
            # ...string) and cannot be settled by rendering.
            #
            # ⚠️ `MODELS` STAYS SET even when we supply our own config. The gallery
            # install is what puts the WEIGHTS and the BACKEND on the volume; it is
            # not merely a way of naming a model. Dropping it once left LocalAI
            # preferring a CUDA backend variant that was never installed, whose
            # failure then put the model into a cooldown that poisoned every
            # fallback in the same pass — so the log blamed a cooldown for a
            # missing backend. Our tuning is applied by overwriting the config
            # file the install writes (see the model-config initContainer), which
            # LocalAI skips re-installing thanks to its `._gallery_*` marker.
            {{- if $s.galleryModel }}
            MODELS: {{ $s.galleryModel | quote }}
            {{- else if not $s.modelConfig }}
            {{- fail (printf "model %s: the localai engine needs either serving.galleryModel (install from the gallery) or serving.modelConfig (define it ourselves)" $name) }}
            {{- end }}
            {{- with $s.backends }}
            EXTERNAL_BACKENDS: {{ join "," . | quote }}
            {{- end }}
            {{- with $eng.backendImagesReleaseTag }}
            # Pins the backend IMAGE tag. Defaults to `latest`, which meant the
            # component that actually executes the model floated while the server
            # image was pinned (ADR-0105).
            BACKEND_IMAGES_RELEASE_TAG: {{ . | quote }}
            {{- end }}
            {{- with $eng.backendGalleries }}
            # Pins the backend GALLERY (default `@master`) and carries the
            # keyless-cosign verification policy. A gallery without a
            # `verification` block installs with no signature check at all.
            BACKEND_GALLERIES: {{ toJson . | quote }}
            {{- end }}
            {{- if $eng.requireBackendIntegrity }}
            REQUIRE_BACKEND_INTEGRITY: "true"
            {{- end }}
            # Both paths live on the weights PVC, so neither the model nor the
            # downloaded backend is re-fetched on a pod restart. BACKENDS_PATH is
            # the one that is easy to forget: LocalAI pulls its inference backend
            # from a gallery at boot, and without persistence that repeats every
            # time the pod moves.
            MODELS_PATH: {{ printf "%s/models" $dir | quote }}
            BACKENDS_PATH: {{ printf "%s/backends" $dir | quote }}
            {{- /* ⚠️ DO NOT SET F16 HERE. It looks like a dtype knob and is not:
                   LocalAI maps it to diffusers' `variant="fp16"`, which selects
                   differently-NAMED files (`*.fp16.safetensors`). A repo that
                   publishes only FP32, as Tongyi-MAI/Z-Image-Turbo does, has no
                   such variant and the backend dies at load with
                   "You are trying to load model files of the `variant=fp16`,
                   but no such modeling files are available". Casting dtype is a
                   different thing entirely. Precision on this fleet comes from
                   the QUANTIZATION in the gallery entry instead. */ -}}
            # ⚠️ EAGER LOAD. Without this the backend loads on the FIRST REQUEST,
            # and `/readyz` — which gates on the model INSTALL, i.e. the download
            # — reports the pod Ready long before it can serve anything. That is
            # how a fully green ArgoCD tree sat in front of a model that returned
            # 500, with 5 MiB of VRAM in use.
            #
            # `LOAD_TO_MEMORY` moves the load into the startup sequence readiness
            # actually waits on, which restores the contract the text engines
            # give us: Ready means loaded. It is also why the startup budget
            # below is hours — the load now happens BEFORE Ready, not after.
            #
            # WATCHDOG_IDLE defaults to false, so once loaded it stays loaded.
            #
            # ⚠️ This is the name INSIDE the model config — `name:` — not the
            # catalog key. They are usually different: LocalAI serves a model
            # under whatever DEFINES it, so a gallery entry is served under the
            # gallery's name (`Z-Image-Turbo`), not ours (`z-image-turbo`). This
            # briefly used the catalog key and asked LocalAI to preload a model
            # that did not exist, which surfaces as the same opaque
            # "load is in cooldown" cascade as a missing backend.
            LOAD_TO_MEMORY: {{ $s.servedModel | default $s.galleryModel | default $name | quote }}
            {{- with $s.extraEnv }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
            {{- end }}
            {{- if $lmcache }}
            {{- toYaml $d.lmcacheEnv | nindent 12 }}
            {{- with ($cfg.lmcache | default dict).env }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
            {{- end }}
            {{- if and $apiKey (eq $akMode "env") }}
            # The engine enforces this itself — no auth-proxy sidecar, for any
            # engine. `optional: false` so the pod waits for ESO rather than
            # starting with an empty key and accepting every request.
            {{ $akEnvName }}:
              secretKeyRef:
                name: {{ $apiKeySecret | quote }}
                key: api_key
                optional: false
            {{- end }}
          {{- end }}
          ports:
            - name: http
              containerPort: 8080
          # A model server that binds its port before the weights finish loading
          # passes a tcpSocket probe in seconds — startup then stops gating and
          # readiness/liveness kill a still-loading pod in a loop. So: httpGet on
          # an endpoint that only 200s once loaded, with a long startup budget;
          # liveness is tcpSocket (kernel-level, won't false-fail a busy server)
          # and only runs once startup has succeeded. `custom: true` or bjw
          # derives its own probe from the Service port.
          probes:
            startup:
              enabled: true
              custom: true
              spec:
                {{- if $eng.warmup }}
                {{- /*
                  ⚠️ READY MUST MEAN LOADED, and for this engine a health endpoint
                  cannot tell us that. MEASURED on the fleet 2026-07-29: at Ready,
                  with LOAD_TO_MEMORY set and no watchdog, `/readyz` returns 200
                  while nvidia-smi reports 5 MiB used and NO GPU PROCESS AT ALL.
                  The weights reach the card only on the first real request, so
                  the first user paid the load (32.03s vs 29.23s warm on 1024x1024).

                  So the startup gate performs an actual generation. It is the
                  only probe that proves the model can serve, which is what the
                  endpoint is about to promise. A 256x256 warmup costs ~3.8s and
                  loads the same resident weights as any other resolution
                  (verified: 5 MiB -> 7505 MiB, and it stays).

                  Cheap failure path: before the HTTP server listens (including
                  the ~3min first-boot backend download) curl fails instantly with
                  connection-refused, so the expensive branch only runs once the
                  server is actually up.
                */}}
                exec:
                  command:
                    - /bin/sh
                    - -c
                    - |
                      curl -sf -m {{ $eng.warmup.timeoutSeconds | default 60 | int }} -o /dev/null \
                        -X POST -H 'Content-Type: application/json' \
                        {{- /* Same condition as the API_KEY env var above — the
                             engine enforces the Bearer natively, so the warmup
                             must present it or every probe 401s and the pod
                             never goes Ready. */}}
                        {{- if and $apiKey (eq $akMode "env") }}
                        -H "Authorization: Bearer ${{ "{" }}{{ $akEnvName }}{{ "}" }}" \
                        {{- end }}
                        -d '{{ merge (dict "model" ($s.servedModel | default $s.galleryModel | default $name)) (deepCopy $eng.warmup.body) | toJson }}' \
                        http://127.0.0.1:8080{{ $eng.warmup.path }}
                periodSeconds: 15
                failureThreshold: {{ $s.startupFailureThreshold | default $eng.startupFailureThreshold | default 120 }}
                timeoutSeconds: {{ add ($eng.warmup.timeoutSeconds | default 60 | int) 10 }}
                {{- else }}
                httpGet: { path: {{ $eng.healthPath | quote }}, port: 8080 }
                periodSeconds: 15
                failureThreshold: {{ $s.startupFailureThreshold | default $eng.startupFailureThreshold | default 120 }}
                timeoutSeconds: 5
                {{- end }}
            readiness:
              enabled: true
              custom: true
              spec:
                httpGet: { path: {{ $eng.healthPath | quote }}, port: 8080 }
                periodSeconds: 15
                timeoutSeconds: 10
                failureThreshold: 3
            liveness:
              enabled: true
              custom: true
              spec:
                tcpSocket: { port: 8080 }
                periodSeconds: 30
                timeoutSeconds: 10
                failureThreshold: 6
          securityContext:
            {{- toYaml $eng.containerSecurityContext | nindent 12 }}
          resources:
            requests:
              cpu: {{ $res.cpuRequest | default "1" | quote }}
              memory: {{ $res.memoryRequest | default "4Gi" | quote }}
            limits:
              cpu: {{ $res.cpuLimit | default "4" | quote }}
              # Host RAM, not VRAM. llama.cpp mmaps the GGUF, so the page cache
              # counts against this limit — size it comfortably above the weights
              # file, or add --no-mmap. vLLM needs headroom for any LMCache CPU pool.
              memory: {{ $res.memoryLimit | default "12Gi" | quote }}
              # The GPU itself. Extended resources are requested via limits.
              nvidia.com/gpu: {{ $gpu.count | default 1 }}

{{- if $seed }}
    # ── The weight seed Job ──────────────────────────────────────────────────
    # An ArgoCD Sync HOOK, not a tracked resource: a plain Job goes perpetually
    # OutOfSync once it completes (its pod template is immutable but its status
    # keeps changing). BeforeHookCreation deletes the previous run first.
    seed:
      type: job
      annotations:
        argocd.argoproj.io/hook: Sync
        argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
        argocd.argoproj.io/sync-wave: "0"
      pod:
        restartPolicy: OnFailure
        # Runs as root because it pip-installs huggingface_hub into system
        # site-packages. Capabilities are dropped and privilege escalation is
        # off; readOnlyRootFilesystem is deliberately absent (pip writes to the
        # rootfs) and KSV-0014 is path-scoped in .trivyignore.yaml.
        securityContext:
          runAsNonRoot: false
          runAsUser: 0
          seccompProfile:
            type: RuntimeDefault
      job:
        backoffLimit: 6
        # Generous: a 16 GB pull over a cold Hub connection is not fast.
        activeDeadlineSeconds: {{ $w.seedDeadlineSeconds | default 7200 }}
      containers:
        seed:
          image:
            repository: {{ $d.seedImage.repository | quote }}
            tag: {{ $d.seedImage.tag | quote }}
            pullPolicy: IfNotPresent
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop:
                - ALL
            runAsNonRoot: false
            runAsUser: 0
            seccompProfile:
              type: RuntimeDefault
          command: ["/bin/sh", "-ec"]
          args:
            - |
              {{- include "inference.seedScript" (dict "weights" $w "dir" $dir) | nindent 14 }}
          {{- if $d.hfToken.enabled }}
          env:
            HF_TOKEN:
              secretKeyRef:
                name: {{ $d.hfToken.secretName | quote }}
                key: {{ $d.hfToken.dataKey | quote }}
                # NEVER optional: an optional secretKeyRef binds empty if the pod
                # beats ESO, and the Job then rate-limits against an anonymous Hub
                # halfway through a multi-GB download. Blocking in
                # ContainerCreating until the secret exists is the better failure.
                optional: false
          {{- end }}
          resources:
            requests: { cpu: "1", memory: 1Gi }
            # ⚠️ Sized by the repo's LARGEST SHARD × concurrent workers, not by
            # its total size. hf_xet buffers per file and `hf download` fans out
            # over 8 workers by default, so a repo of three ~10 GB shards can
            # need several times what a single 16 GB GGUF needs.
            #
            # 6Gi was the fleet default and it OOM-killed the Z-Image-Turbo seed
            # (exit 137, four times in six minutes) — the first model whose
            # shards are that large. It is now a per-model knob; raise
            # `weights.seedMemoryLimit` AND cap `weights.seedMaxWorkers` rather
            # than only throwing RAM at it.
            # Do NOT set HF_XET_HIGH_PERFORMANCE.
            limits:   { cpu: "2", memory: {{ $w.seedMemoryLimit | default "6Gi" | quote }} }

{{- end }}

  service:
    main:
      controller: main
      type: ClusterIP
      labels:
        ai-helm.adorsys-gis.github.io/model: {{ $name | quote }}
      ports:
        http:
          port: 8080
          targetPort: 8080

  persistence:
{{- if $seed }}
    # The pre-seeded RWX weights volume: writable for the seed Job, read-only
    # for the model.
    model-store:
      enabled: true
      existingClaim: {{ $pvcName | quote }}
      advancedMounts:
        main:
          model:
            - path: /models
              readOnly: true
        seed:
          seed:
            - path: /models
{{- else }}
    # ⚠️ WRITABLE, and mounted only by the model. This engine downloads its own
    # weights AND its inference backend at start-up, so a read-only mount would
    # fail on first boot — and without persistence it would re-download both on
    # every restart. There is no seed Job to co-mount it.
    model-store:
      enabled: true
      existingClaim: {{ $pvcName | quote }}
      advancedMounts:
        main:
          model:
            - path: /models
{{- if $s.modelConfig }}
          model-config:
            - path: /models
{{- end }}
{{- end }}
    {{- if and $apiKey (eq $akMode "file") }}
    # This engine reads the Bearer from a FILE (llama.cpp's --api-key-file), so
    # the Secret is mounted rather than passed as an env var.
    api-key:
      enabled: true
      type: secret
      name: {{ $apiKeySecret | quote }}
      advancedMounts:
        main:
          model:
            - path: {{ $akPath | quote }}
              readOnly: true
    {{- end }}
    {{- if $s.modelConfig }}
    # Our LocalAI model config. Mounted read-only OUTSIDE the weights volume:
    # MODELS_PATH is writable and LocalAI owns it, so a config living there would
    # be fighting the engine for the same directory.
    model-config:
      enabled: true
      type: configMap
      name: {{ printf "%s-config" $name | quote }}
      advancedMounts:
        main:
          model-config:
            - path: /config
              readOnly: true
    {{- end }}
    {{- if $eng.devShm }}
    # vLLM's worker processes talk over shared memory; the 64 MB default /dev/shm
    # is not enough and the failure mode is an opaque hang during engine start.
    dshm:
      enabled: true
      type: emptyDir
      medium: Memory
      sizeLimit: {{ $s.shmSize | default "2Gi" | quote }}
      advancedMounts:
        main:
          model:
            - path: /dev/shm
    {{- end }}
{{- end -}}
