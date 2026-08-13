{{/*
ai-models.requireCatalog

Preflight guard. Renders nothing; hard-fails if the model catalog is absent.

Since ADR-0126 the catalog does not live in this chart — it is supplied by
`ai-helm-values environments/prod/values/models.yaml` through the `aii-models`
Application's `$values` source, and this chart's own values.yaml is an empty
skeleton. That source is mounted with `ignoreMissingValueFiles: true`, so a
file that is missing, renamed, or unreadable does NOT fail the ArgoCD render on
its own — it silently yields the chart defaults.

Without this guard those defaults render PERFECTLY VALIDLY: an ApplicationSet
whose list generator has one element (the backends child) and no model
elements. The ApplicationSet controller would then treat every model child as
deleted and prune the whole gateway catalog — every AIGatewayRoute, every
BackendTrafficPolicy — on a green sync. The destination guard below does not
catch it: `argocd.destination` defaults to "home-remote" and renders happily.

So an empty catalog is a render failure instead. The `aii-models` Application
goes ComparisonError, stops syncing, and every running model child is left
exactly as it is — which is the only safe direction for this particular
failure.

Input: the root context.
*/}}
{{- define "ai-models.requireCatalog" -}}
{{- $missing := list -}}
{{- if not .Values.models -}}{{- $missing = append $missing "models" -}}{{- end -}}
{{- if not .Values.backends -}}{{- $missing = append $missing "backends" -}}{{- end -}}
{{- if not .Values.gatewayRef -}}{{- $missing = append $missing "gatewayRef" -}}{{- end -}}
{{- if not (.Values.argocd.destination).namespace -}}{{- $missing = append $missing "argocd.destination.namespace" -}}{{- end -}}
{{- if $missing -}}
{{- fail (printf "\n\n  REFUSING TO RENDER: the model catalog is missing (%s).\n\n  This chart carries no catalog of its own (ADR-0126) — it is supplied by\n  ai-helm-values at environments/prod/values/models.yaml via the aii-models\n  Application's $values source. Rendering without it would emit an\n  ApplicationSet with NO model children, and the controller would prune every\n  model route on the gateway.\n\n  If you are rendering locally, pass that file with -f. If you are seeing this\n  from ArgoCD, the values repo file is missing or unparseable — fix it there;\n  the running model children are untouched until it is.\n" (join ", " $missing)) -}}
{{- end -}}
{{- end -}}

{{/*
ai-models.argocd.destinationClusterRef

Emits the ArgoCD destination cluster identity line — `name: <ctx>` or
`server: <url>` — and HARD-FAILS the render if it resolves to the
in-cluster API server, unless `allowInCluster: true` is set.

This enforces the repo invariant (ADR-0017): every workload Application
this repo generates must target the home-remote cluster ("home-remote"),
never the cluster ArgoCD itself runs in. The guard makes an accidental
`in-cluster` (or `https://kubernetes.default.svc`) destination a render
failure rather than a silent mis-deploy.

  Controllable knobs (under `argocd.destination`):
    name            cluster context name        (default "home-remote")
    server          cluster API URL             (alternative to name)
    allowInCluster  escape hatch, default false (set true to permit in-cluster)

Input  : the `argocd.destination` dict.
Output : exactly one YAML line — `name: "…"` or `server: "…"`.
         The caller appends the `namespace:` line itself.

Usage:
  destination:
    {{ include "ai-models.argocd.destinationClusterRef" .Values.argocd.destination | nindent 4 }}
    namespace: {{ .Values.argocd.destination.namespace | quote }}
*/}}
{{- define "ai-models.argocd.destinationClusterRef" -}}
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
