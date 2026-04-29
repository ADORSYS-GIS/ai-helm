{{/*
External Secrets Configuration Chart
Helper functions for external-secrets configuration
*/}}

{{/*
Return the proper namespace for the component.
Allows override via .Values.namespace.name
*/}}
{{- define "external-secrets.namespace" -}}
{{- if .Values.namespace -}}
{{- .Values.namespace.name -}}
{{- else -}}
{{- include "common.names.namespace" . -}}
{{- end -}}
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
{{- .Values.serviceAccount.bootstrap.name | default (printf "%s-bootstrap" (include "common.names.fullname" .)) -}}
{{- end -}}

{{/*
Return the ClusterRole name for the ClusterSecretStore.
*/}}
{{- define "external-secrets.clusterRoleName" -}}
{{- printf "%s-bootstrap-reader" (include "common.names.fullname" .) -}}
{{- end -}}

{{/*
Return the ClusterRoleBinding name for the ClusterSecretStore.
*/}}
{{- define "external-secrets.clusterRoleBindingName" -}}
{{- printf "%s-bootstrap-reader" (include "common.names.fullname" .) -}}
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