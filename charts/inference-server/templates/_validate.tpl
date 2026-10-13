{{/*
Fail-fast guards. This leaf is never deployed with its own defaults — the
orchestrator (charts/inference) always injects a full values block — so a
missing field here means the orchestrator's expansion is broken, and failing the
render is far better than shipping a StatefulSet with an empty model name.

Same convention as charts/ai-model's guards; see that chart's aigatewayroute.yaml.
*/}}
{{- define "inference-server.validate" -}}
{{- if not .Values.model.name -}}
{{- fail "inference-server: .Values.model.name is required (the StatefulSet/Service name and the served model id). This chart is not meant to be deployed directly — add an entry to charts/inference/values.yaml instead." -}}
{{- end -}}
{{- if not (has .Values.model.engine (list "llamacpp" "vllm" "localai")) -}}
{{- fail (printf "inference-server: .Values.model.engine must be one of [llamacpp vllm localai], got %q" .Values.model.engine) -}}
{{- end -}}
{{- if not .Values.model.storagePath -}}
{{- fail "inference-server: .Values.model.storagePath is required (the sub-directory of the weights volume holding this model)" -}}
{{- end -}}
{{- if and .Values.pvc.enabled (not .Values.pvc.name) -}}
{{- fail "inference-server: .Values.pvc.name is required when pvc.enabled" -}}
{{- end -}}
{{- if and .Values.pvc.enabled (not .Values.pvc.size) -}}
{{- fail "inference-server: .Values.pvc.size is required when pvc.enabled (size the claim above the weights — see the model's catalog entry)" -}}
{{- end -}}
{{- /* A fromEndpoints selector with no namespace label is scoped to the POLICY's
       own namespace by Cilium, and one with no pod labels admits the whole
       namespace — both render valid YAML and silently admit the wrong peers. */ -}}
{{- range .Values.networkPolicy.allowFromEndpoints -}}
{{- if not .namespace -}}
{{- fail "inference-server: every networkPolicy.allowFromEndpoints entry needs a `namespace` (without it Cilium scopes the selector to the inference namespace itself)" -}}
{{- end -}}
{{- if not .matchLabels -}}
{{- fail (printf "inference-server: networkPolicy.allowFromEndpoints entry for namespace %q needs non-empty `matchLabels` — to admit a whole namespace use allowFromNamespaces" .namespace) -}}
{{- end -}}
{{- end -}}
{{- if and .Values.apiKey.enabled (not .Values.apiKey.secretName) -}}
{{- fail "inference-server: .Values.apiKey.secretName is required when apiKey.enabled" -}}
{{- end -}}
{{- end -}}

{{/* The logical model name — served model id, StatefulSet and Service name. */}}
{{- define "inference-server.name" -}}
{{- include "inference-server.validate" . -}}
{{- .Values.model.name -}}
{{- end -}}
