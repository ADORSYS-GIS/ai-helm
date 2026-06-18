{{/*
Base name for all resources (release-independent so service DNS is stable).
*/}}
{{- define "lci.name" -}}
{{- .Values.nameOverride | default "lightbridge-ci" -}}
{{- end -}}

{{- define "lci.controlPlane.name" -}}
{{- printf "%s-control-plane" (include "lci.name" .) -}}
{{- end -}}

{{- define "lci.web.name" -}}
{{- printf "%s-web" (include "lci.name" .) -}}
{{- end -}}

{{- define "lci.neo4j.name" -}}
{{- printf "%s-neo4j" (include "lci.name" .) -}}
{{- end -}}

{{/*
Common labels.
*/}}
{{- define "lci.labels" -}}
app.kubernetes.io/part-of: lightbridge-code-intelligence
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/*
Per-component selector labels. Call with (dict "ctx" . "component" "web").
*/}}
{{- define "lci.selectorLabels" -}}
app.kubernetes.io/name: {{ include "lci.name" .ctx }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/*
Internal cluster DNS of the control-plane service (used as the web authN backend).
*/}}
{{- define "lci.controlPlane.url" -}}
{{- printf "http://%s.%s.svc.cluster.local:%d" (include "lci.controlPlane.name" .) .Release.Namespace (int .Values.controlPlane.port) -}}
{{- end -}}
