{{/*
External Secrets Configuration Chart
Helper functions using BJW-S common library
*/}}

{{/*
Expand the name of the chart.
*/}}
{{- define "external-secrets.name" -}}
{{- include "common.names.name" . -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "external-secrets.fullname" -}}
{{- include "common.names.fullname" . -}}
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "external-secrets.chart" -}}
{{- include "common.names.chart" . -}}
{{- end -}}

{{/*
Return the proper namespace for the component.
*/}}
{{- define "external-secrets.namespace" -}}
{{- if .Values.namespace -}}
{{- .Values.namespace.name -}}
{{- else -}}
{{- include "common.names.namespace" . -}}
{{- end -}}
{{- end -}}

{{/*
Return the proper labels for ExternalSecrets resources.
*/}}
{{- define "external-secrets.labels" -}}
{{- include "common.labels.standard" . -}}
{{- end -}}

{{/*
Return the ClusterSecretStore name.
*/}}
{{- define "external-secrets.clusterSecretStoreName" -}}
{{- .Values.clusterSecretStore.name | default "bootstrap-secrets" -}}
{{- end -}}

{{/*
Return the ServiceAccount name for the ClusterSecretStore.
*/}}
{{- define "external-secrets.serviceAccountName" -}}
{{- .Values.serviceAccount.bootstrap.name | default (printf "%s-bootstrap" (include "external-secrets.fullname" .)) -}}
{{- end -}}

{{/*
Return the ClusterRole name for the ClusterSecretStore.
*/}}
{{- define "external-secrets.clusterRoleName" -}}
{{- printf "%s-bootstrap-reader" (include "external-secrets.fullname" .) -}}
{{- end -}}

{{/*
Return the ClusterRoleBinding name for the ClusterSecretStore.
*/}}
{{- define "external-secrets.clusterRoleBindingName" -}}
{{- printf "%s-bootstrap-reader" (include "external-secrets.fullname" .) -}}
{{- end -}}

{{/*
Return the sync wave annotation for ArgoCD.
Usage: {{ include "external-secrets.syncWave" (dict "wave" "1" "context" $) }}
*/}}
{{- define "external-secrets.syncWave" -}}
{{- $wave := .wave | toString -}}
{{- if .context.Values.global -}}
{{- if .context.Values.global.syncWave -}}
{{- $wave = .context.Values.global.syncWave | toString -}}
{{- end -}}
{{- end -}}
argocd.argoproj.io/sync-wave: {{ $wave | quote }}
{{- end -}}

{{/*
Create annotations for resources.
*/}}
{{- define "external-secrets.annotations" -}}
{{- if .Values.global -}}
{{- if .Values.global.annotations -}}
{{- toYaml .Values.global.annotations -}}
{{- end -}}
{{- end -}}
{{- end -}}