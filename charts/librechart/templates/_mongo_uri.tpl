{{- define "mongo_uri" -}}
{{- $replicas := $.Values.global.mongo.replicaCount | int -}}
{{- $releaseName := $.Release.Name -}}
{{- $port := "27017" -}}
mongodb://{{- range $i := until $replicas -}}
{{ $releaseName }}-db-{{ $i }}.{{ $releaseName }}-db-headless:{{ $port }}{{- if ne (add1 $i) $replicas }},{{ end -}}
{{- end }}
{{- end -}}