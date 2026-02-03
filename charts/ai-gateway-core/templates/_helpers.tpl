{{- define "ai-gateway.tlsListener" }}
{{- if .Values.tls.enabled }}
- name: https
  protocol: HTTPS
  port: 443
  tls:
    mode: Terminate
    certificateRefs:
      - kind: Secret
        name: {{ .Values.tls.secretName }}
{{- end }}
{{- end }}