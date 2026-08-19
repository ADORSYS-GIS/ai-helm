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
{{- else if eq $kind "image" -}}
{{- dict "inputModalities" (list "text") "outputModalities" (list "image") | toJson -}}
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
{{- else if eq $strategy "flatPerRequest" -}}
  {{- /* Image models price per image ($/image), not per token. Emit as
         flat per-request price in the prompt field for OpenRouter-shape compat. */ -}}
  {{- $perReq := index $std "effectivePerRequest" | default 0 -}}
  {{- $_ := set $out "prompt"     (printf "%.8f" $perReq) -}}
  {{- $_ := set $out "completion" (printf "%.8f" $perReq) -}}
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

Walks .Values.models, skips entries whose `kind` is in .Values.excludeKinds,
whose `enabled: false`, or whose `disableExternal: true`. Emits one object per
remaining model under `data: [...]`.

⚠️ The `disableExternal` skip is not cosmetic. This catalog is served on the
PUBLIC host (api.ai.camer.digital), while a `disableExternal: true` model is
deliberately attached only to the `api-internal` listener — reachable from
LibreChat and other in-cluster callers, not from outside. Advertising it here
told external clients about models they cannot use: selecting one returned
`404 No matching route found`, which reads as a broken model rather than an
intentional restriction. Verified live 2026-07-27: 6 of 31 advertised models
were internal-only in exactly this way.

Output: full JSON string `{"data":[...]}`.
*/}}
{{- define "ai-models-info.catalog" -}}
{{- $excluded := default (list) .Values.excludeKinds -}}
{{- $defaults := default (dict) .Values.catalogDefaults -}}
{{- $defCtx := default 128000 $defaults.contextLength -}}
{{- $defMaxTok := default 8192 $defaults.maxCompletionTokens -}}
{{- $maxCtx := default 1000000 $defaults.maxContextLength -}}
{{- $entries := list -}}
{{- range $name, $cfg := .Values.models -}}
  {{- $kind := default "text" $cfg.kind -}}
  {{- if and (not (eq $cfg.enabled false)) (not (has $kind $excluded)) (not (eq (default false $cfg.disableExternal) true)) -}}
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
           hard-capped at catalogDefaults.maxContextLength (1000000). top_provider
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

{{/*
Anthropic-shape model catalog for Claude Code's gateway model discovery.

Claude Code (with CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1) issues
`GET <ANTHROPIC_BASE_URL>/v1/models?limit=1000` at startup and adds the results
to its `/model` picker. It reads only two fields per entry -- `id` and the
optional `display_name` -- from a top-level `data` array. Everything else in
the OpenRouter-shape catalog (pricing, architecture, context_length) is
ignored here, which is why this is a separate renderer rather than a reshaping
of `ai-models-info.catalog`.

⚠️ THE `id` PREFIX IS LOAD-BEARING, NOT DECORATION. Claude Code keeps an entry
only when its `id` contains "claude" or "anthropic", matched case-insensitively
ANYWHERE in the string, and silently drops the rest -- the filter exists so a
gateway backed by a shared key doesn't surface every model to every user.
NONE of this platform's model ids contain either substring, so without a prefix
this endpoint renders an empty picker and the whole feature is inert.
Provider-prefixed ids are explicitly supported by the protocol (its own
examples are `vertex_ai/claude-sonnet-4-6` and
`bedrock/anthropic.claude-sonnet-4-5`), which is what `anthropicCatalog.idPrefix`
uses.

⚠️ CONSEQUENCE: the id advertised here is the id Claude Code sends back as the
`model` on `/anthropic/v1/messages`. The gateway MUST accept the prefixed form
(or strip the prefix on the way in), or a developer picks a model from the
picker and every request fails. See the chart README before changing the
prefix. `display_name` carries the human-readable name, so the prefix is not
what anyone reads in the picker.

Applies the SAME exclusions as the OpenRouter catalog -- `enabled: false`,
`kind` in `excludeKinds`, and `disableExternal: true` -- because this is served
on the same public host, and an internal-only model must not become externally
discoverable just because it is reached through a different path.
*/}}
{{- define "ai-models-info.anthropicCatalog" -}}
{{- $excluded := default (list) .Values.excludeKinds -}}
{{- $cfgRoot := default (dict) .Values.anthropicCatalog -}}
{{- $prefix := default "" $cfgRoot.idPrefix -}}
{{- $entries := list -}}
{{- range $name, $cfg := .Values.models -}}
  {{- $kind := default "text" $cfg.kind -}}
  {{- if and (not (eq $cfg.enabled false)) (not (has $kind $excluded)) (not (eq (default false $cfg.disableExternal) true)) -}}
    {{- $info := default (dict) $cfg.info -}}
    {{- $entry := dict
        "id"           (printf "%s%s" $prefix $name)
        "display_name" (default $name (index $info "displayName"))
    -}}
    {{- $entries = append $entries $entry -}}
  {{- end -}}
{{- end -}}
{{- dict "data" $entries | toJson -}}
{{- end -}}
