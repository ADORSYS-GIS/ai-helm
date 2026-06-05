{{/*
model-serving helpers.
*/}}

{{/* The logical model / InferenceService name (drives the Knative FQDN). */}}
{{- define "model-serving.name" -}}
{{- .Values.model.name | required "model.name is required" -}}
{{- end -}}

{{/* The pvc:// storageUri KServe mounts (no runtime download). */}}
{{- define "model-serving.storageUri" -}}
{{- printf "pvc://%s/%s" .Values.pvc.name .Values.model.storagePath -}}
{{- end -}}

{{/*
The env list for the model container: LMCache (when enabled) + the API key
(from the ESO-owned Secret) + any extraEnv. Rendered as a YAML sequence.
*/}}
{{- define "model-serving.modelEnv" -}}
{{- if .Values.lmcache.enabled }}
- name: LMCACHE_USE_EXPERIMENTAL
  value: {{ .Values.lmcache.useExperimental | toString | title | quote }}
- name: LMCACHE_LOCAL_CPU
  value: {{ .Values.lmcache.localCpu | toString | title | quote }}
- name: LMCACHE_MAX_LOCAL_CPU_SIZE
  value: {{ .Values.lmcache.maxLocalCpuSizeGb | toString | quote }}
{{- end }}
{{- if .Values.apiKey.enabled }}
- name: {{ .Values.apiKey.envVar }}
  valueFrom:
    secretKeyRef:
      name: {{ .Values.apiKey.secretName }}
      key: {{ .Values.apiKey.dataKey }}
{{- end }}
{{- with .Values.inferenceService.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end -}}
