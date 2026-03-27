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
{{- $p := . -}}
{{- printf "((double(int(input_tokens) - int(cached_input_tokens)) * %v) + (double(int(cached_input_tokens)) * %v) + (double(int(output_tokens)) * %v))" (float64 $p.inputPer1M) (float64 (default 0 $p.cachedInputPer1M)) (float64 $p.outputPer1M) -}}
{{- end -}}

{{- define "ai-models.flatCostBranch" -}}
{{- $p := . -}}
{{- printf "(double(int(total_tokens)) * %v)" (float64 $p.effectivePer1M) -}}
{{- end -}}

{{- define "ai-models.costExpression" -}}
{{- $routeName := .routeName -}}
{{- $routeConfig := .routeConfig -}}
{{- $pricing := $routeConfig.pricing -}}
{{- if not $pricing -}}
{{- fail (printf "Route '%s' is missing pricing configuration" $routeName) -}}
{{- end -}}
{{- $expr := "" -}}
{{- if eq $pricing.strategy "weighted" -}}
{{- $expr = include "ai-models.weightedCostBranch" $pricing.standard -}}
{{- else if eq $pricing.strategy "tieredWeighted" -}}
{{- if not $pricing.longContext -}}
{{- fail (printf "Route '%s' uses tieredWeighted pricing but is missing pricing.longContext" $routeName) -}}
{{- end -}}
{{- $threshold := int $pricing.thresholdTokens -}}
{{- $standardBranch := include "ai-models.weightedCostBranch" $pricing.standard -}}
{{- $longBranch := include "ai-models.weightedCostBranch" $pricing.longContext -}}
{{- $expr = printf "((int(input_tokens) > %d) ? %s : %s)" $threshold $longBranch $standardBranch -}}
{{- else if eq $pricing.strategy "flat" -}}
{{- $expr = include "ai-models.flatCostBranch" $pricing.standard -}}
{{- else -}}
{{- fail (printf "Route '%s' has unsupported pricing.strategy '%v'" $routeName $pricing.strategy) -}}
{{- end -}}
{{- printf "((%s > 0.0) ? %s : 0.0)" $expr $expr -}}
{{- end -}}

