{{/*
Expand the name of the chart.
*/}}
{{- define "aisix.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified app name. `releaseName: aisix` in charts/apps means this
normally collapses to plain `aisix` — which is what the EAIG Backend's
`fqdn.hostname: aisix.converse.svc.cluster.local` depends on.
*/}}
{{- define "aisix.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "aisix.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "aisix.labels" -}}
helm.sh/chart: {{ include "aisix.chart" . }}
{{ include "aisix.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "aisix.selectorLabels" -}}
app.kubernetes.io/name: {{ include "aisix.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
The OTLP traces endpoint handed to the `observability_exporters` entry.
See values.yaml for why this has to go through an `otel-collector`
ExternalName alias instead of Alloy's own FQDN.
*/}}
{{- define "aisix.otlpEndpoint" -}}
{{- $o := .Values.observability.otlp -}}
{{- if $o.endpoint -}}
{{- $o.endpoint -}}
{{- else -}}
{{- printf "http://%s:4318/v1/traces" $o.alias.name -}}
{{- end -}}
{{- end }}
