{{/*
Expand the name of the chart.
*/}}
{{- define "keycloak-backup.name" -}}
{{- default .Chart.Name .Values.global.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "keycloak-backup.fullname" -}}
{{- if .Values.global.fullnameOverride }}
{{- .Values.global.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.global.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "keycloak-backup.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels - uses common library for global labels
*/}}
{{- define "keycloak-backup.labels" -}}
{{- $root := . -}}
{{- $labels := dict -}}
{{- $_ := set $labels "helm.sh/chart" (include "keycloak-backup.chart" $root) -}}
{{- $_ := set $labels "app.kubernetes.io/managed-by" "Helm" -}}
{{- range $key, $value := .Values.globalLabels }}
{{- $_ := set $labels $key $value -}}
{{- end }}
{{- include "bjw-s.common.lib.metadata.allLabels" . | fromYaml | merge $labels | toYaml }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "keycloak-backup.selectorLabels" -}}
{{- dict "app.kubernetes.io/name" (include "keycloak-backup.name" .) "app.kubernetes.io/instance" .Release.Name | toYaml }}
{{- end }}

{{/*
CronJob name
*/}}
{{- define "keycloak-backup.cronjobName" -}}
{{- printf "%s-backup" (include "keycloak-backup.fullname" .) }}
{{- end }}

{{/*
Restore Job name
*/}}
{{- define "keycloak-backup.restoreJobName" -}}
{{- printf "%s-restore" (include "keycloak-backup.fullname" .) }}
{{- end }}



{{/*
Image specification to image string
*/}}
{{- define "keycloak-backup.image" -}}
{{- $root := .rootContext -}}
{{- $imageSpec := .imageSpec -}}
{{- $image := "" -}}

{{- if $imageSpec.digest -}}
  {{- /* Use digest if provided */ -}}
  {{- if $imageSpec.registry -}}
    {{- $image = printf "%s/%s@%s" $imageSpec.registry $imageSpec.repository $imageSpec.digest -}}
  {{- else -}}
    {{- $image = printf "%s@%s" $imageSpec.repository $imageSpec.digest -}}
  {{- end -}}
{{- else -}}
  {{- /* Use tag if provided, otherwise default to "16" */ -}}
  {{- $tag := $imageSpec.tag | default "16" -}}
  {{- if $imageSpec.registry -}}
    {{- $image = printf "%s/%s:%s" $imageSpec.registry $imageSpec.repository $tag -}}
  {{- else -}}
    {{- $image = printf "%s:%s" $imageSpec.repository $tag -}}
  {{- end -}}
{{- end -}}

{{- $image -}}
{{- end }}

{{/*
Validate required values - PRODUCTION READY VERSION
*/}}
{{- define "keycloak-backup.validateValues" -}}
{{- $errors := list -}}

{{- /* Validation for CronJob if enabled */ -}}
{{- if .Values.controllers.cronjob.enabled -}}
  {{- /* Basic CronJob validation */ -}}
  {{- if not .Values.keycloak.secretName -}}
    {{- $errors = append $errors "keycloak.secretName is required when controllers.cronjob.enabled is true" -}}
  {{- end -}}
  {{- if not .Values.s3.secretName -}}
    {{- $errors = append $errors "s3.secretName is required when controllers.cronjob.enabled is true" -}}
  {{- end -}}
  {{- /* Cron schedule validation */ -}}
  {{- if not .Values.controllers.cronjob.schedule -}}
    {{- $errors = append $errors "controllers.cronjob.schedule is required when cronjob is enabled" -}}
  {{- end -}}
{{- end -}}

{{- /* Validation for Job if enabled AND restore.object is set */ -}}
{{- if and .Values.controllers.job.enabled .Values.restore.object -}}
  {{- /* Basic Job validation only when restoring */ -}}
  {{- if not .Values.keycloak.secretName -}}
    {{- $errors = append $errors "keycloak.secretName is required when restoring (controllers.job.enabled and restore.object are set)" -}}
  {{- end -}}
  {{- if not .Values.s3.secretName -}}
    {{- $errors = append $errors "s3.secretName is required when restoring (controllers.job.enabled and restore.object are set)" -}}
  {{- end -}}
  {{- if not .Values.restore.object -}}
    {{- $errors = append $errors "restore.object is required when controllers.job.enabled is true" -}}
  {{- end -}}
{{- end -}}

{{- /* Check if both controllers are disabled */ -}}
{{- if and (not .Values.controllers.cronjob.enabled) (not .Values.controllers.job.enabled) -}}
  {{- $errors = append $errors "At least one controller must be enabled (controllers.cronjob.enabled or controllers.job.enabled)" -}}
{{- end -}}

{{- /* Output errors */ -}}
{{- if $errors -}}
{{- printf "\nVALIDATION FAILED:\n%s\n" (join "\n" $errors) | fail -}}
{{- end -}}
{{- end -}}

{{/*
Get controller values with fallback to legacy values for backward compatibility
*/}}
{{- define "keycloak-backup.getControllerValues" -}}
{{- $root := .root -}}
{{- $controllerType := .controllerType -}}
{{- $result := dict -}}
{{- if eq $controllerType "cronjob" -}}
  {{- if $root.Values.controllers.cronjob -}}
    {{- $result = $root.Values.controllers.cronjob -}}
  {{- else -}}
    {{- /* Fallback to legacy backup values */ -}}
    {{- $_ := set $result "enabled" $root.Values.backup.enabled -}}
    {{- $_ := set $result "schedule" $root.Values.backup.schedule -}}
    {{- $_ := set $result "concurrencyPolicy" $root.Values.backup.concurrencyPolicy -}}
    {{- $_ := set $result "successfulJobsHistoryLimit" $root.Values.backup.successfulJobsHistoryLimit -}}
    {{- $_ := set $result "failedJobsHistoryLimit" $root.Values.backup.failedJobsHistoryLimit -}}
    {{- $_ := set $result "startingDeadlineSeconds" 30 -}}
    {{- $_ := set $result "ttlSecondsAfterFinished" $root.Values.backup.ttlSecondsAfterFinished -}}
    {{- $_ := set $result "terminationGracePeriodSeconds" $root.Values.backup.terminationGracePeriodSeconds -}}
    {{- $_ := set $result "resources" $root.Values.backup.resources -}}
    {{- $_ := set $result "nodeSelector" $root.Values.backup.nodeSelector -}}
    {{- $_ := set $result "tolerations" $root.Values.backup.tolerations -}}
    {{- $_ := set $result "affinity" $root.Values.backup.affinity -}}
    {{- $_ := set $result "livenessProbe" $root.Values.backup.livenessProbe -}}
    {{- $_ := set $result "image" (dict "repository" "postgres" "tag" "16" "pullPolicy" "IfNotPresent") -}}
  {{- end -}}
{{- else if eq $controllerType "job" -}}
  {{- if $root.Values.controllers.job -}}
    {{- $result = $root.Values.controllers.job -}}
  {{- else -}}
    {{- /* Fallback to legacy restore values */ -}}
    {{- $_ := set $result "enabled" $root.Values.restoreLegacy.enabled -}}
    {{- $_ := set $result "resources" $root.Values.restoreLegacy.resources -}}
    {{- $_ := set $result "nodeSelector" $root.Values.restoreLegacy.nodeSelector -}}
    {{- $_ := set $result "tolerations" $root.Values.restoreLegacy.tolerations -}}
    {{- $_ := set $result "affinity" $root.Values.restoreLegacy.affinity -}}
    {{- $_ := set $result "terminationGracePeriodSeconds" $root.Values.restoreLegacy.terminationGracePeriodSeconds -}}
    {{- $_ := set $result "ttlSecondsAfterFinished" $root.Values.restoreLegacy.ttlSecondsAfterFinished -}}
    {{- $_ := set $result "backoffLimit" $root.Values.restoreLegacy.backoffLimit -}}
    {{- $_ := set $result "annotations" (dict "helm.sh/hook" "post-install" "helm.sh/hook-delete-policy" "hook-succeeded,before-hook-creation") -}}
    {{- $_ := set $result "image" (dict "repository" "postgres" "tag" "16" "pullPolicy" "IfNotPresent") -}}
  {{- end -}}
{{- end -}}
{{- $result | toYaml -}}
{{- end -}}
