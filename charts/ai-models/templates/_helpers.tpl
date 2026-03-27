{{- define "ai-models.priceScale" -}}
{{- printf "%d" (int (round (mulf (default 0 .) 1000) 0)) -}}
{{- end -}}

{{- define "ai-models.weightedCostBranch" -}}
{{- $pricing := . -}}
{{- $inputScaled := include "ai-models.priceScale" $pricing.inputPer1M -}}
{{- $cachedScaled := include "ai-models.priceScale" (default 0 $pricing.cachedInputPer1M) -}}
{{- $outputScaled := include "ai-models.priceScale" $pricing.outputPer1M -}}
{{- printf "((max((int(input_tokens) - int(cached_input_tokens)), 0) * %s) + (int(cached_input_tokens) * %s) + (int(output_tokens) * %s))" $inputScaled $cachedScaled $outputScaled -}}
{{- end -}}

{{- define "ai-models.flatCostBranch" -}}
{{- $pricing := . -}}
{{- $effectiveScaled := include "ai-models.priceScale" $pricing.effectivePer1M -}}
{{- printf "(int(total_tokens) * %s)" $effectiveScaled -}}
{{- end -}}

{{- define "ai-models.costExpression" -}}
{{- $routeName := .routeName -}}
{{- $routeConfig := .routeConfig -}}
{{- $pricing := $routeConfig.pricing -}}
{{- if not $pricing -}}
{{- fail (printf "Route '%s' is missing pricing configuration" $routeName) -}}
{{- end -}}
{{- if eq $pricing.strategy "weighted" -}}
{{- printf "(%s / 1000)" (include "ai-models.weightedCostBranch" $pricing.standard) -}}
{{- else if eq $pricing.strategy "tieredWeighted" -}}
{{- if not $pricing.longContext -}}
{{- fail (printf "Route '%s' uses tieredWeighted pricing but is missing pricing.longContext" $routeName) -}}
{{- end -}}
{{- $threshold := int $pricing.thresholdTokens -}}
{{- $standardBranch := include "ai-models.weightedCostBranch" $pricing.standard -}}
{{- $longBranch := include "ai-models.weightedCostBranch" $pricing.longContext -}}
{{- printf "(((int(input_tokens) > %d) ? %s : %s) / 1000)" $threshold $longBranch $standardBranch -}}
{{- else if eq $pricing.strategy "flat" -}}
{{- printf "(%s / 1000)" (include "ai-models.flatCostBranch" $pricing.standard) -}}
{{- else -}}
{{- fail (printf "Route '%s' has unsupported pricing.strategy '%v'" $routeName $pricing.strategy) -}}
{{- end -}}
{{- end -}}

{{/*
Builds a QuotaPolicy-compatible CEL costExpression for a given model's pricing.

QuotaPolicy costExpression uses raw token floats:
  input_tokens, cached_input_tokens, output_tokens, total_tokens

Prices in values.yaml are per-1M tokens. priceScale multiplies by 1000,
so the result is in micro-USD (USD * 1e6) matching the monthly budget limits.
*/}}
{{- define "ai-models.quotaCostExpression" -}}
{{- $routeName := .routeName -}}
{{- $routeConfig := .routeConfig -}}
{{- $pricing := $routeConfig.pricing -}}
{{- if not $pricing -}}
{{- fail (printf "Route '%s' is missing pricing configuration" $routeName) -}}
{{- end -}}
{{- if eq $pricing.strategy "weighted" -}}
{{- $inputScaled := include "ai-models.priceScale" $pricing.standard.inputPer1M -}}
{{- $cachedScaled := include "ai-models.priceScale" (default 0 $pricing.standard.cachedInputPer1M) -}}
{{- $outputScaled := include "ai-models.priceScale" $pricing.standard.outputPer1M -}}
{{- printf "(max(input_tokens - cached_input_tokens, 0.0) * %s + cached_input_tokens * %s + output_tokens * %s) / 1000.0" $inputScaled $cachedScaled $outputScaled -}}
{{- else if eq $pricing.strategy "tieredWeighted" -}}
{{- if not $pricing.longContext -}}
{{- fail (printf "Route '%s' uses tieredWeighted pricing but is missing pricing.longContext" $routeName) -}}
{{- end -}}
{{- $threshold := int $pricing.thresholdTokens -}}
{{- $sIn := include "ai-models.priceScale" $pricing.standard.inputPer1M -}}
{{- $sCached := include "ai-models.priceScale" (default 0 $pricing.standard.cachedInputPer1M) -}}
{{- $sOut := include "ai-models.priceScale" $pricing.standard.outputPer1M -}}
{{- $lIn := include "ai-models.priceScale" $pricing.longContext.inputPer1M -}}
{{- $lCached := include "ai-models.priceScale" (default 0 $pricing.longContext.cachedInputPer1M) -}}
{{- $lOut := include "ai-models.priceScale" $pricing.longContext.outputPer1M -}}
{{- printf "(input_tokens > %d.0 ? (max(input_tokens - cached_input_tokens, 0.0) * %s + cached_input_tokens * %s + output_tokens * %s) : (max(input_tokens - cached_input_tokens, 0.0) * %s + cached_input_tokens * %s + output_tokens * %s)) / 1000.0" $threshold $lIn $lCached $lOut $sIn $sCached $sOut -}}
{{- else if eq $pricing.strategy "flat" -}}
{{- $effectiveScaled := include "ai-models.priceScale" $pricing.standard.effectivePer1M -}}
{{- printf "total_tokens * %s / 1000.0" $effectiveScaled -}}
{{- else -}}
{{- fail (printf "Route '%s' has unsupported pricing.strategy '%v'" $routeName $pricing.strategy) -}}
{{- end -}}
{{- end -}}
