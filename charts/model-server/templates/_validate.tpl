{{/*
Fail-fast guards. This leaf is never deployed with its own defaults — the
orchestrator (charts/model-serving) always injects a full values block — so a
missing field here means the orchestrator's expansion is broken, and failing the
render is far better than shipping a StatefulSet with an empty model name.

Same convention as charts/ai-model's guards; see that chart's aigatewayroute.yaml.
*/}}
{{- define "model-server.validate" -}}
{{- if not .Values.model.name -}}
{{- fail "model-server: .Values.model.name is required (the StatefulSet/Service name and the served model id). This chart is not meant to be deployed directly — add an entry to charts/model-serving/values.yaml instead." -}}
{{- end -}}
{{- if not (has .Values.model.engine (list "llamacpp" "vllm" "zimage")) -}}
{{- fail (printf "model-server: .Values.model.engine must be one of [llamacpp vllm zimage], got %q" .Values.model.engine) -}}
{{- end -}}
{{- if not .Values.model.storagePath -}}
{{- fail "model-server: .Values.model.storagePath is required (the sub-directory of the weights volume holding this model)" -}}
{{- end -}}
{{- if and .Values.pvc.enabled (not .Values.pvc.name) -}}
{{- fail "model-server: .Values.pvc.name is required when pvc.enabled" -}}
{{- end -}}
{{- if and .Values.pvc.enabled (not .Values.pvc.size) -}}
{{- fail "model-server: .Values.pvc.size is required when pvc.enabled (size the claim above the weights — see the model's catalog entry)" -}}
{{- end -}}
{{- if and .Values.apiKey.enabled (not .Values.apiKey.secretName) -}}
{{- fail "model-server: .Values.apiKey.secretName is required when apiKey.enabled" -}}
{{- end -}}
{{- end -}}

{{/* The logical model name — served model id, StatefulSet and Service name. */}}
{{- define "model-server.name" -}}
{{- include "model-server.validate" . -}}
{{- .Values.model.name -}}
{{- end -}}
