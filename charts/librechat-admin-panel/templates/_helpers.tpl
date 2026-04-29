{{/*
Expand the name of the chart.
*/}}
{{- define "librechat-admin-panel.fullname" -}}
{{- include "common.names.fullname" . -}}
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "librechat-admin-panel.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "librechat-admin-panel.labels" -}}
{{ include "common.labels.standard" . }}
{{- end -}}
