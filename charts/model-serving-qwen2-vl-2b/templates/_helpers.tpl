{{/*
model-serving-qwen2-vl-2b helpers (used by the chart's OWN templates/ — the PVC,
ExternalSecrets, Caddyfile ConfigMap. The workload's env/args live in the
bjw-template values under `modelServing:`).
*/}}

{{/* The logical model name — the served model id + the StatefulSet/Service name. */}}
{{- define "model-serving-qwen2-vl-2b.name" -}}
{{- .Values.model.name | required "model.name is required" -}}
{{- end -}}