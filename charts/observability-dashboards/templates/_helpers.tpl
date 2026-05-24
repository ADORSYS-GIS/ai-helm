{{/*
Standard labels applied to every CR owned by this chart.
*/}}
{{- define "observability-dashboards.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/*
The instanceSelector match used by every GrafanaDashboard/GrafanaFolder to
bind to the Grafana CR.
*/}}
{{- define "observability-dashboards.instanceSelectorYaml" -}}
matchLabels:
  {{ .Values.grafana.instanceLabel.key }}: {{ .Values.grafana.instanceLabel.value | quote }}
{{- end -}}
