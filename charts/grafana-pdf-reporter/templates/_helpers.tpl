{{/*
grafana-pdf-reporter standard labels.
*/}}
{{- define "grafana-pdf-reporter.labels" -}}
app.kubernetes.io/name: {{ .Values.name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: observability
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
