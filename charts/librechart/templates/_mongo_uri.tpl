{{- define "mongo_uri" -}}
{{- $dbReplicaMembers := dig "db" "replicaSet" "members" nil $.Values -}}
{{- $legacyReplicaCount := dig "db" "replicaCount" nil $.Values -}}
{{- $globalReplicaCount := dig "global" "mongo" "replicaCount" nil $.Values -}}
{{- $replicas := (coalesce $dbReplicaMembers $legacyReplicaCount $globalReplicaCount 1) | int -}}
{{- $dbReplicaSetName := dig "db" "replicaSet" "name" nil $.Values -}}
{{- $globalReplicaSetName := dig "global" "mongo" "replicaSetName" nil $.Values -}}
{{- $replicaSetName := default "rs0" (coalesce $dbReplicaSetName $globalReplicaSetName) -}}
{{- $releaseName := $.Release.Name -}}
{{- $port := "27017" -}}
mongodb://{{- range $i := until $replicas -}}
{{ $releaseName }}-db-{{ $i }}.{{ $releaseName }}-db-headless:{{ $port }}{{- if ne (add1 $i) $replicas }},{{ end -}}
{{- end }}
{{- end -}}
