{{/*
model-serving-qwen3-5 helpers (used by the chart's OWN templates/ — the PVC and
ExternalSecrets. The workload's container/args live in the bjw-template values
under `modelServing:`).
*/}}

{{/* The logical model name — the served model id + the StatefulSet/Service name. */}}
{{- define "model-serving-qwen3-5.name" -}}
{{- .Values.model.name | required "model.name is required" -}}
{{- end -}}
