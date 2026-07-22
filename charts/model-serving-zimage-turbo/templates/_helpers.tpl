{{/*
model-serving-zimage-turbo helpers (used by the chart's OWN templates/ — the PVC,
seed Job, ExternalSecrets. The workload's env/args live in the bjw-template
values under `modelServing:`).
*/}}

{{/* The logical model name — the served model id + the STS/Service name. */}}
{{- define "model-serving-zimage-turbo.name" -}}
{{- .Values.model.name | required "model.name is required" -}}
{{- end -}}
