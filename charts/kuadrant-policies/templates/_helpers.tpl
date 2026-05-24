{{/*
Build a list of Authorino `when` predicates that EXCLUDE tokens whose `azp`
claim equals any of the supplied service-account client IDs.

A token is considered a "service account" if its `azp` matches one of the
allowlisted clients. Predicates are AND'd together — the step runs only when
the token's azp differs from EVERY entry in the list, i.e. is a human user.

Input: list of client-id strings.
Output: YAML list of predicate objects, no leading indent.

Usage in a step:
  {{- include "kuadrant-policies.skipSAWhen" $clients | nindent 8 }}
*/}}
{{- define "kuadrant-policies.skipSAWhen" -}}
{{- range . }}
- selector: auth.identity.azp
  operator: neq
  value: {{ . | quote }}
{{- end }}
{{- end -}}

{{/*
Render a single Authorino AuthConfig step (metadata / authorization entry).

Strips the chart-private `_skipForServiceAccounts` marker, and if set true with
a non-empty service-account allowlist, merges SA-exclusion predicates into the
step's `when:` block (preserving any user-supplied `when:` entries).

Input: dict with keys
  step:      the step's spec (map)
  saClients: list of service-account client IDs (may be empty/nil)

Output: YAML for the step body (no leading indent).
*/}}
{{- define "kuadrant-policies.authStep" -}}
{{- $step := .step -}}
{{- $skipSAs := default false (index $step "_skipForServiceAccounts") -}}
{{- $clean := omit $step "_skipForServiceAccounts" -}}
{{- if and $skipSAs .saClients -}}
{{- $existingWhen := default (list) (index $clean "when") -}}
{{- $saWhen := list -}}
{{- range .saClients -}}
{{- $saWhen = append $saWhen (dict "selector" "auth.identity.azp" "operator" "neq" "value" .) -}}
{{- end -}}
{{- $clean = set (deepCopy $clean) "when" (concat $existingWhen $saWhen) -}}
{{- end -}}
{{- toYaml $clean -}}
{{- end -}}
