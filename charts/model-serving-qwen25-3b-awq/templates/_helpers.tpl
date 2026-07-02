{{/*
model-serving-qwen25-3b-awq helpers (used by the chart's OWN templates/ — the PVC,
seed Job, ExternalSecrets. The workload's env/args live in the bjw-template
values under `modelServing:`).
*/}}

{{/* The logical model name — the served model id + the StatefulSet/Service name. */}}
{{- define "model-serving-qwen25-3b-awq.name" -}}
{{- .Values.model.name | required "model.name is required" -}}
{{- end -}}
