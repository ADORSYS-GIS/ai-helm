{{- define "network-policy.ingress-rules" -}}
{{- $policy := . -}}
{{- if or $policy.ingressNamespaces $policy.ingressIntraNamespace $policy.ingressPods $policy.ingress -}}
ingress:
  # Namespace-based ingress (abstraction)
  {{- range $ns := $policy.ingressNamespaces }}
  - from:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: {{ .name | default . }}
    {{- if .ports }}
    ports:
      {{- toYaml .ports | nindent 6 }}
    {{- end }}
  {{- end }}
  # Intra-namespace ingress (abstraction)
  {{- if $policy.ingressIntraNamespace }}
  - from:
      - podSelector: {}
  {{- end }}
  {{- if $policy.ingressPods }}
  - from:
      - podSelector:
          {{- if typeIs "map[string]interface {}" $policy.ingressPods }}
          matchLabels:
            {{- toYaml $policy.ingressPods | nindent 12 }}
          {{- else }}
          {}
          {{- end }}
  {{- end }}
  # Raw ingress rules (backward compatibility)
  {{- if $policy.ingress }}
  {{- toYaml $policy.ingress | nindent 2 }}
  {{- end }}
{{- end }}
{{- end -}}

{{- define "network-policy.egress-rules" -}}
{{- $policy := . -}}
{{- if or $policy.egressDns $policy.egressIntraNamespace $policy.egressNamespaces $policy.egressServices $policy.egressInternalServices $policy.egressExternal $policy.egress -}}
egress:
  # DNS handling (abstraction) - Hardened to kube-system
  {{- if $policy.egressDns }}
  - to:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: kube-system
    ports:
      - protocol: UDP
        port: 53
      - protocol: TCP
        port: 53
  {{- end }}
  # Intra-namespace egress (abstraction)
  {{- if $policy.egressIntraNamespace }}
  - to:
      - podSelector: {}
  {{- end }}
  # Namespace-based egress (abstraction)
  {{- range $ns := $policy.egressNamespaces }}
  - to:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: {{ .name | default . }}
    {{- if .ports }}
    ports:
      {{- toYaml .ports | nindent 6 }}
    {{- end }}
  {{- end }}
  # Internal service dependencies (abstraction) - supports both egressServices and egressInternalServices
  {{- range $svc := $policy.egressServices }}
  - to:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: {{ .namespace | default . }}
    {{- if .ports }}
    ports:
      {{- toYaml .ports | nindent 6 }}
    {{- end }}
  {{- end }}
  {{- range $svc := $policy.egressInternalServices }}
  - to:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: {{ .namespace | default . }}
    {{- if .ports }}
    ports:
      {{- toYaml .ports | nindent 6 }}
    {{- end }}
  {{- end }}
  # External egress CIDRs (abstraction)
  {{- range $ext := $policy.egressExternal }}
  - to:
      - ipBlock:
          cidr: {{ .cidr }}
          {{- if .except }}
          except:
            {{- toYaml .except | nindent 10 }}
          {{- end }}
    {{- if .ports }}
    ports:
      {{- toYaml .ports | nindent 6 }}
    {{- end }}
  {{- end }}
  # Raw egress rules (backward compatibility)
  {{- if $policy.egress }}
  {{- toYaml $policy.egress | nindent 2 }}
  {{- end }}
{{- end }}
{{- end -}}

{{- define "network-policy.full" -}}
{{- $policy := .Values.networkPolicy -}}
{{- if $policy.enabled -}}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ $policy.name | default .Chart.Name }}
  namespace: {{ $policy.namespace | default .Release.Namespace }}
  labels:
    app.kubernetes.io/name: {{ $.Chart.Name }}
    app.kubernetes.io/instance: {{ $.Release.Name }}
    app.kubernetes.io/managed-by: {{ $.Release.Service }}
spec:
  podSelector:
    {{- if $policy.podSelector }}
    {{- toYaml $policy.podSelector | nindent 4 }}
    {{- else }}
    matchLabels: {}
    {{- end }}
  policyTypes:
    {{- if $policy.policyTypes }}
    {{- toYaml $policy.policyTypes | nindent 4 }}
    {{- else }}
    - Ingress
    - Egress
    {{- end }}
  
  {{- include "network-policy.ingress-rules" $policy | nindent 2 }}
  {{- include "network-policy.egress-rules" $policy | nindent 2 }}
{{- end -}}
{{- end -}}
