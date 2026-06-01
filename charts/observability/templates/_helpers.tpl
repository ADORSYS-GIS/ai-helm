{{/*
observability.argocd.destinationClusterRef

Emits the ArgoCD destination cluster identity line — `name: <ctx>` or
`server: <url>` — and HARD-FAILS the render if it resolves to the in-cluster
API server, unless `allowInCluster: true`. Enforces ADR-0017: every workload
Application this repo generates targets home-remote, never the cluster ArgoCD
runs in. Mirror of coder/librechart/ai-models' helper.
*/}}
{{- define "observability.argocd.destinationClusterRef" -}}
{{- $d := . | default dict -}}
{{- $name := $d.name | default "" -}}
{{- $server := $d.server | default "" -}}
{{- $allow := $d.allowInCluster | default false -}}
{{- $inClusterServers := list "https://kubernetes.default.svc" "https://kubernetes.default.svc:443" -}}
{{- $isInCluster := or (eq $name "in-cluster") (has $server $inClusterServers) -}}
{{- if and $isInCluster (not $allow) -}}
{{- fail (printf "\n\n  REFUSING TO RENDER: ArgoCD destination resolved to the in-cluster API\n  (name=%q server=%q).\n\n  Workloads in this repo must target the home-remote cluster, never the\n  cluster ArgoCD runs in. Either:\n    - set argocd.destination.name to the remote context (default \"home-remote\"), or\n    - if you REALLY mean in-cluster, set argocd.destination.allowInCluster: true.\n\n  See ADR-0017.\n" $name $server) -}}
{{- end -}}
{{- if $server -}}
server: {{ $server | quote }}
{{- else -}}
name: {{ $name | default "home-remote" | quote }}
{{- end -}}
{{- end -}}
