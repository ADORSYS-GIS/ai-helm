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
hf download {{ $w.hfRepo }} --revision {{ $rev }} --local-dir "$MODEL_DIR"
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
    {{- $args = concat $args (list "--api-key-file" "/etc/model-api-key/api_key") -}}
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
         ⚠️ CORS: vLLM's `--allowed-origins` takes a JSON list and is applied only
         when explicitly set, because it has NOT yet been verified against a
         running vLLM pod on this fleet. Verify on the first deploy, then make it
         a fleet default like the llama.cpp one. */ -}}
  {{- with $s.allowedOrigins -}}
    {{- $args = concat $args (list "--allowed-origins" .) -}}
  {{- end -}}
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
{{- $engine := required (printf "model %s: `engine` is required (llamacpp|vllm)" $name) $cfg.engine -}}
{{- if not (has $engine (list "llamacpp" "vllm")) -}}
{{- fail (printf "model %s: unknown engine %q — expected llamacpp or vllm. Add a profile in charts/model-serving/templates/_helpers.tpl if you mean to introduce one." $name $engine) -}}
{{- end -}}
{{- $eng := index $d.engines $engine -}}
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

serviceMonitor:
{{- toYaml $d.serviceMonitor | nindent 2 }}

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
            repository: {{ $eng.image.repository | quote }}
            tag: {{ $eng.image.tag | quote }}
            pullPolicy: {{ $eng.image.pullPolicy | default "IfNotPresent" | quote }}
          args:
            {{- include "model-serving.serverArgs" (dict "name" $name "engine" $engine "serving" $s "dir" $dir "lmcache" $lmcache "apiKey" $apiKey "security" $sec) | trim | nindent 12 }}
          {{- if or $lmcache (and $apiKey (eq $engine "vllm")) }}
          env:
            {{- if $lmcache }}
            {{- toYaml $d.lmcacheEnv | nindent 12 }}
            {{- with ($cfg.lmcache | default dict).env }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
            {{- end }}
            {{- if and $apiKey (eq $engine "vllm") }}
            # vLLM's own OpenAI server enforces this itself — no auth-proxy
            # sidecar. `optional: false` so the pod waits for ESO rather than
            # starting with an empty key and accepting every request.
            VLLM_API_KEY:
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
            # hf_xet is memory-hungry on large files; 2Gi OOM-killed a seed pod
            # historically. Do NOT set HF_XET_HIGH_PERFORMANCE.
            limits:   { cpu: "2", memory: 6Gi }

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
    {{- if and $apiKey (eq $engine "llamacpp") }}
    # llama-server reads the Bearer from a FILE (--api-key-file), so the Secret
    # is mounted rather than passed as an env var.
    api-key:
      enabled: true
      type: secret
      name: {{ $apiKeySecret | quote }}
      advancedMounts:
        main:
          model:
            - path: /etc/model-api-key
              readOnly: true
    {{- end }}
    {{- if eq $engine "vllm" }}
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
