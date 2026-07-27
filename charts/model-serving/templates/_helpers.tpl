{{/*
═══════════════════════════════════════════════════════════════════════════════
 model-serving helpers — the ENGINE PROFILES.

 This file is the machinery that lets a ~15-line catalog entry become a complete
 model deployment. It expands one `models:` entry into the full values block the
 `model-server` leaf (and its bjw-template subchart) needs.

 Why here and not in the leaf: a Helm parent cannot compute SUBCHART values at
 render time. The old per-model charts hit that wall and worked around it by
 hardcoding the seed repo/glob in the bjw values with a "⚠️ keep in sync with
 model.hfRepo" comment — a standing invitation to ship a model that serves one
 set of weights and downloads another. The orchestrator has no such limit: it
 writes each child's values as a YAML string, so every derived value is computed
 exactly once, from one source of truth.

 Adding an engine = adding a profile here + a `ci/<engine>-values.yaml` fixture
 in charts/model-server. Nothing else in the repo changes.
═══════════════════════════════════════════════════════════════════════════════
*/}}

{{/*
model-serving.argocd.destinationClusterRef

Emits the ArgoCD destination cluster identity line and HARD-FAILS if it resolves
to the in-cluster API server without an explicit opt-in. Enforces ADR-0017: the
workloads this repo generates target home-remote, never the cluster ArgoCD runs
in. Identical contract to `ai-models.argocd.destinationClusterRef`.

⚠️ Note the two-tier split: the ApplicationSet itself is a CONTROL object and
lands in-cluster/argocd (via the charts/apps `controlPlane: true` entry); the
CHILD Applications it generates are workloads and come through this guard.
*/}}
{{- define "model-serving.argocd.destinationClusterRef" -}}
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
model-serving.storagePath — the sub-directory of the weights volume for a model.
Defaults to the HF repo's last path segment, so `jabbatheduck/OpenMythos-GGUF`
becomes `OpenMythos-GGUF`. Overridable per model.
Input: the model's `weights` dict.
*/}}
{{- define "model-serving.storagePath" -}}
{{- .storagePath | default (last (splitList "/" (required "weights.hfRepo is required" .hfRepo))) -}}
{{- end -}}


{{/*
model-serving.seedScript — the weight-download script for the seed Job.

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
{{- define "model-serving.seedScript" -}}
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
echo "Seed complete."
{{- end -}}


{{/*
model-serving.serverArgs — the engine command line.

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

zimage: our own Rust/Candle image-generation server (images/z-image-turbo-server,
  ADR-0100). Bare flags again, but the vocabulary is image geometry and sampling
  rather than context and slots — there is no `contextSize` to require here.

Input: dict "name" <name> "engine" <engine> "serving" <serving> "dir" <modelDir> "lmcache" <lmcache>
Output: a YAML list of strings.
*/}}
{{- define "model-serving.serverArgs" -}}
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
{{- else if eq .engine "zimage" -}}
  {{- /* Image generation (ADR-0100). The image's entrypoint IS the server
         binary, so these are bare flags — same shape as llama.cpp, different
         vocabulary: there is no context window, no parallel slots and no
         reasoning here, only image geometry and sampling.

         ⚠️ The server VALIDATES these at start-up and exits non-zero if they are
         inconsistent (dimensions must divide by 16, defaults must not exceed
         --max-size, steps 1..50, guidance 0..20). That is deliberate: a bad
         geometry fails the deploy loudly instead of 400-ing every request.

         The Bearer arrives as API_KEY in the environment (see the engine's
         `apiKey.mode`), so it never appears on the command line. CORS is NOT
         configurable in this server — see the profile in values.yaml. */ -}}
  {{- $args = concat $args (list
      "--model-dir" $dir
      "--host" "0.0.0.0"
      "--port" "8080"
      "--max-size" (toString (default 1024 $s.maxImageSize))
      "--default-width" (toString (default 1024 $s.defaultWidth))
      "--default-height" (toString (default 1024 $s.defaultHeight))
      "--num-steps" (toString (default 8 $s.numSteps))
      "--guidance-scale" (toString (default 5.0 $s.guidanceScale))) -}}
{{- end -}}
{{- $args = concat $args (default (list) $s.extraArgs) -}}
{{- range $args }}
- {{ . | quote }}
{{- end }}
{{- end -}}


{{/*
model-serving.childValues — the whole values block for one model-server child.

Input: dict "root" $ "name" <modelName> "cfg" <modelConfig>
Output: YAML (unindented; the caller indents it into the ApplicationSet element).
*/}}
{{- define "model-serving.childValues" -}}
{{- $root := .root -}}
{{- $name := .name -}}
{{- $cfg := .cfg -}}
{{- $d := $root.Values.defaults -}}
{{- $engine := required (printf "model %s: `engine` is required (llamacpp|vllm|zimage)" $name) $cfg.engine -}}
{{- if not (has $engine (list "llamacpp" "vllm" "zimage")) -}}
{{- fail (printf "model %s: unknown engine %q — expected llamacpp, vllm or zimage. Add a profile in charts/model-serving/templates/_helpers.tpl if you mean to introduce one." $name $engine) -}}
{{- end -}}
{{- $eng := index $d.engines $engine -}}
{{- /* Per-model image override, merged key-by-key over the engine profile's.
       Lets a catalog entry pin a digest once the model is load-gated, or run a
       one-off build, without forking the profile for every other model on it. */ -}}
{{- $image := merge (deepCopy ($cfg.image | default dict)) (deepCopy $eng.image) -}}
{{- $w := required (printf "model %s: `weights` is required" $name) $cfg.weights -}}
{{- $s := $cfg.serving | default dict -}}
{{- $res := $cfg.resources | default dict -}}
{{- $gpu := $d.gpu -}}
{{- $storagePath := include "model-serving.storagePath" $w -}}
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
{{- toYaml $d.hfToken | nindent 2 }}

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
      containers:
        model:
          image:
            repository: {{ $image.repository | quote }}
            tag: {{ $image.tag | quote }}
            pullPolicy: {{ $image.pullPolicy | default "IfNotPresent" | quote }}
          args:
            {{- include "model-serving.serverArgs" (dict "name" $name "engine" $engine "serving" $s "dir" $dir "lmcache" $lmcache "apiKey" $apiKey "security" $sec "apiKeyPath" $akPath) | trim | nindent 12 }}
          {{- if or $lmcache (and $apiKey (eq $akMode "env")) }}
          env:
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
                httpGet: { path: {{ $eng.healthPath | quote }}, port: 8080 }
                periodSeconds: 15
                failureThreshold: {{ $s.startupFailureThreshold | default 120 }}
                timeoutSeconds: 5
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
              {{- include "model-serving.seedScript" (dict "weights" $w "dir" $dir) | nindent 14 }}
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
