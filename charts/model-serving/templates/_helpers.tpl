{{/*
Chart name.
*/}}
{{- define "model-serving.name" -}}
{{- default .Chart.Name .Values.global.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Primary resource name — drives the InferenceService name and related resources.
Prefers fullnameOverride, then model.name.
*/}}
{{- define "model-serving.fullname" -}}
{{- if .Values.global.fullnameOverride }}
  {{- .Values.global.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
  {{- .Values.model.name | required "model.name is required" | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
ServingRuntime name. Prefers servingRuntime.nameOverride, then <fullname>-runtime.
*/}}
{{- define "model-serving.runtimeName" -}}
{{- if .Values.servingRuntime.nameOverride }}
  {{- .Values.servingRuntime.nameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
  {{- printf "%s-runtime" (include "model-serving.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Runtime name referenced by the InferenceService.
Prefers inferenceService.runtime, then falls back to the chart-managed runtime.
*/}}
{{- define "model-serving.inferenceRuntimeRef" -}}
{{- if .Values.inferenceService.runtime }}
  {{- .Values.inferenceService.runtime }}
{{- else }}
  {{- include "model-serving.runtimeName" . }}
{{- end }}
{{- end }}

{{/*
PVC name for the model store.
Prefers model.storage.pvc.nameOverride, then <fullname>-model-store.
*/}}
{{- define "model-serving.pvcName" -}}
{{- if .Values.model.storage.pvc.nameOverride }}
  {{- .Values.model.storage.pvc.nameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
  {{- printf "%s-model-store" (include "model-serving.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Resolved storageUri for the InferenceService.
When PVC storage is enabled the pvc:// URI is constructed from the PVC name
and optional subPath. Otherwise the raw model.storageUri is used.
*/}}
{{- define "model-serving.resolvedStorageUri" -}}
{{- if .Values.model.storage.pvc.enabled }}
  {{- $pvcName := include "model-serving.pvcName" . }}
  {{- if .Values.model.storage.pvc.subPath }}
    {{- printf "pvc://%s/%s" $pvcName .Values.model.storage.pvc.subPath }}
  {{- else }}
    {{- printf "pvc://%s" $pvcName }}
  {{- end }}
{{- else }}
  {{- required "model.storageUri is required when model.storage.pvc.enabled is false" .Values.model.storageUri }}
{{- end }}
{{- end }}

{{/*
Download destination path inside the Job's PVC mount.
Mirrors the subPath logic so the storage-initializer writes to the right place.
*/}}
{{- define "model-serving.downloaderDestDir" -}}
{{- if .Values.model.storage.pvc.subPath }}
  {{- printf "/mnt/models/%s" .Values.model.storage.pvc.subPath }}
{{- else }}
  {{- "/mnt/models" }}
{{- end }}
{{- end }}

{{/*
Common labels applied to all chart-managed resources.
*/}}
{{- define "model-serving.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
app.kubernetes.io/name: {{ include "model-serving.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
