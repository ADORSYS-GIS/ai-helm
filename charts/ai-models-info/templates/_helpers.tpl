{{/*
ai-models-info.modalitiesFor — map our `kind` value to OpenRouter
`architecture.{input_modalities, output_modalities}`.
Input: model kind string.
Output: dict { inputModalities: [...], outputModalities: [...] }
*/}}
{{- define "ai-models-info.modalitiesFor" -}}
{{- $kind := default "text" . -}}
{{- if eq $kind "multimodal" -}}
{{- dict "inputModalities" (list "text" "image") "outputModalities" (list "text") | toJson -}}
{{- else if eq $kind "embedding" -}}
{{- dict "inputModalities" (list "text") "outputModalities" (list "text") | toJson -}}
{{- else if eq $kind "reranker" -}}
{{- dict "inputModalities" (list "text") "outputModalities" (list "text") | toJson -}}
{{- else -}}
{{- /* text and unknown default to text-only */ -}}
{{- dict "inputModalities" (list "text") "outputModalities" (list "text") | toJson -}}
{{- end -}}
{{- end -}}

{{/*
ai-models-info.usdPerToken — convert a per-1M-token USD price to
per-token USD string with enough precision (8 decimal places).
Returns "0.00000000" for nil / missing input.
*/}}
{{- define "ai-models-info.usdPerToken" -}}
{{- $perM := . -}}
{{- if $perM -}}
{{- printf "%.10f" (divf $perM 1000000.0) -}}
{{- else -}}
{{- "0.00000000" -}}
{{- end -}}
{{- end -}}

{{/*
ai-models-info.pricingFor — build the OpenRouter `pricing` block for a
model. Honors both `weighted` and `flat` strategies; emits `prompt`,
`completion`, and optionally `input_cache_read`.

Input: model's `pricing` dict.
Output: dict-as-JSON.
*/}}
{{- define "ai-models-info.pricingFor" -}}
{{- $pricing := . -}}
{{- $strategy := default "weighted" $pricing.strategy -}}
{{- $std := default (dict) $pricing.standard -}}
{{- $out := dict -}}
{{- if eq $strategy "flat" -}}
  {{- $eff := index $std "effectivePer1M" -}}
  {{- $_ := set $out "prompt"     (include "ai-models-info.usdPerToken" $eff) -}}
  {{- $_ := set $out "completion" (include "ai-models-info.usdPerToken" $eff) -}}
{{- else -}}
  {{- /* weighted (and tieredWeighted falls through to standard pricing) */ -}}
  {{- $in  := index $std "inputPer1M" -}}
  {{- $ot  := index $std "outputPer1M" -}}
  {{- $cir := index $std "cachedInputPer1M" -}}
  {{- $_ := set $out "prompt"     (include "ai-models-info.usdPerToken" $in) -}}
  {{- $_ := set $out "completion" (include "ai-models-info.usdPerToken" $ot) -}}
  {{- if $cir }}{{- $_ := set $out "input_cache_read" (include "ai-models-info.usdPerToken" $cir) }}{{- end -}}
{{- end -}}
{{- $out | toJson -}}
{{- end -}}

{{/*
ai-models-info.catalog — render the OpenRouter-shape catalog as JSON.

Walks .Values.models, skips entries whose `kind` is in .Values.excludeKinds
or whose `enabled: false`. Emits one object per remaining model under
`data: [...]`.

Output: full JSON string `{"data":[...]}`.
*/}}
{{- define "ai-models-info.catalog" -}}
{{- $excluded := default (list) .Values.excludeKinds -}}
{{- $defaults := default (dict) .Values.catalogDefaults -}}
{{- $defCtx := default 128000 $defaults.contextLength -}}
{{- $defMaxTok := default 8192 $defaults.maxCompletionTokens -}}
{{- $maxCtx := default 400000 $defaults.maxContextLength -}}
{{- $entries := list -}}
{{- range $name, $cfg := .Values.models -}}
  {{- $kind := default "text" $cfg.kind -}}
  {{- if and (not (eq $cfg.enabled false)) (not (has $kind $excluded)) -}}
    {{- $info := default (dict) $cfg.info -}}
    {{- $entry := dict
        "id"      $name
        "name"    (default $name (index $info "displayName"))
    -}}

    {{- /* Pricing */ -}}
    {{- if $cfg.pricing -}}
      {{- $_ := set $entry "pricing" (include "ai-models-info.pricingFor" $cfg.pricing | fromJson) -}}
    {{- end -}}

    {{- /* Architecture (modalities) */ -}}
    {{- $mods := include "ai-models-info.modalitiesFor" $kind | fromJson -}}
    {{- $_ := set $entry "architecture" (dict
        "input_modalities"  $mods.inputModalities
        "output_modalities" $mods.outputModalities
    ) -}}

    {{- /* context_length + top_provider — always emitted. Per-model
           `info.contextLength` / `info.maxOutputTokens` override the
           chart-wide catalogDefaults (128000 / 8192). context_length is
           hard-capped at catalogDefaults.maxContextLength (400000). top_provider
           mirrors context_length (OpenRouter shape). */ -}}
    {{- $ctx := min (default $defCtx $info.contextLength) $maxCtx -}}
    {{- $maxTok := default $defMaxTok $info.maxOutputTokens -}}
    {{- $_ := set $entry "context_length" $ctx -}}
    {{- $_ := set $entry "top_provider" (dict
        "context_length"        $ctx
        "max_completion_tokens" $maxTok
    ) -}}

    {{- /* Optional supported_parameters */ -}}
    {{- if $info.supportedParameters -}}
      {{- $_ := set $entry "supported_parameters" $info.supportedParameters -}}
    {{- end -}}

    {{- $entries = append $entries $entry -}}
  {{- end -}}
{{- end -}}
{{- dict "data" $entries | toJson -}}
{{- end -}}
