{{- define "H.user" -}}
{{- include "common.tplvalues.render" ( dict "value" .Values.headers.user "context" $ ) -}}
{{- end }}

{{- define "H.tier" -}}
{{- include "common.tplvalues.render" ( dict "value" .Values.headers.tier "context" $ ) -}}
{{- end }}

{{- define "H.tenant" -}}
{{- include "common.tplvalues.render" ( dict "value" .Values.headers.tenant "context" $ ) -}}
{{- end }}

{{- define "H.model" -}}
{{- include "common.tplvalues.render" ( dict "value" .Values.headers.model "context" $ ) -}}
{{- end }}

# lookup with wildcard fallback
{{- define "limit.get" -}}
{{- $tier := .tier -}}
{{- $kind := .kind -}}    {{/* reqPerMin | tokensPerMin | tokensPerMonth */}}
{{- $model := .model -}}
{{- $t := get .context.Values.tiers $tier -}}
{{- $m := (get (get $t $kind) $model) | default (get (get $t $kind) "*" ) -}}
{{- if $m -}}
{{- $m | int64 -}}
{{- else -}}
{{- printf "%s-%s-%s" $tier $kind $model -}}
{{- end -}}
{{- end }}

# is model allowed for tier?
{{- define "allowed" -}}
{{- $tier := .tier -}}
{{- $model := .model -}}
{{- $allow := (get (get .context.Values.tiers $tier) "allow") | default (list) -}}
{{- if has "*" $allow -}}true{{- else -}}{{ ternary "true" "false" (has $model $allow) }}{{- end -}}
{{- end }}
