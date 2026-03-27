{{/*
metadataKeySafe turns a model name into a metadata key safe string.
Example: "gpt-5.4-mini" -> "cost_gpt_5_4_mini"
*/}}
{{- define "ai-models.metadataKeySafe" -}}
{{- printf "cost_%s" (. | replace "-" "_" | replace "." "_") -}}
{{- end -}}

{{- define "ai-models.priceScale" -}}
{{- printf "%d" (int (round (mulf (default 0 .) 1000) 0)) -}}
{{- end -}}

{{- define "ai-models.weightedCostBranch" -}}
{{- $pricing := . -}}
{{- $inputScaled := include "ai-models.priceScale" $pricing.inputPer1M -}}
{{- $cachedScaled := include "ai-models.priceScale" (default 0 $pricing.cachedInputPer1M) -}}
{{- $outputScaled := include "ai-models.priceScale" $pricing.outputPer1M -}}
{{- printf "((((int(input_tokens) - int(cached_input_tokens)) > 0 ? (int(input_tokens) - int(cached_input_tokens)) : 0) * %s) + (int(cached_input_tokens) * %s) + (int(output_tokens) * %s))" $inputScaled $cachedScaled $outputScaled -}}
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

