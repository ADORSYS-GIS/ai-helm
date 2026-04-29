{{/*
Expand the name of the chart.
*/}}
{{- define "librechat-admin-panel.fullname" -}}
{{- default .Chart.Name .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "librechat-admin-panel.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "librechat-admin-panel.labels" -}}
helm.sh/chart: {{ include "librechat-admin-panel.chart" . }}
{{ include "librechat-admin-panel.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "librechat-admin-panel.selectorLabels" -}}
app.kubernetes.io/name: {{ include "librechat-admin-panel.fullname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
