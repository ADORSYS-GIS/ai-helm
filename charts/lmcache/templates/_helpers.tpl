{{/*
This template serves as a blueprint for all the other templates.
*/}}
{{- define "lmcache.hardcodedValues" -}}
# -- Set the nameOverride based on the release name if no override has been set
{{- if not .Values.global.nameOverride }}
global:
  nameOverride: "{{ .Release.Name }}"
{{- end }}
{{- end -}}

