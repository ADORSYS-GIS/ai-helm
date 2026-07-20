{{/*
llm-d helpers (used by the chart OWN templates/ — the PVC, the Envoy
ConfigMap, and the ExternalSecret. The workload config lives in the subchart
values under llmdRouter: / modelServing:).
*/}}

{{/* The Envoy ConfigMap name — referenced by both the ConfigMap template and
the EPP Deployment volume (via llmdRouter.router.proxy.volumes). Keeping it in
one place so they can't drift. */}}
{{- define "llm-d.envoyConfigMapName" -}}
{{- .Values.llmdRouter.router.proxy.configMapName | default "llm-d-epp-envoy" -}}
{{- end -}}
