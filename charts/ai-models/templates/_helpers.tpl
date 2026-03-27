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

{{- define "ai-models.celToken" -}}
{{- printf "(has(%s) ? int(%s) : 0)" . . -}}
{{- end -}}

{{- define "ai-models.weightedCostBranch" -}}
{{- $p := . -}}
{{- $in := mulf $p.inputPer1M 1000000 | printf "%.0f" -}}
{{- $ca := mulf (default 0 $p.cachedInputPer1M) 1000000 | printf "%.0f" -}}
{{- $out := mulf $p.outputPer1M 1000000 | printf "%.0f" -}}
{{- $inVar := include "ai-models.celToken" "input_tokens" -}}
{{- $caVar := include "ai-models.celToken" "cached_input_tokens" -}}
{{- $outVar := include "ai-models.celToken" "output_tokens" -}}
{{- printf "((%s - %s) * %s + %s * %s + %s * %s)" $inVar $caVar $in $caVar $ca $outVar $out -}}
{{- end -}}

{{- define "ai-models.flatCostBranch" -}}
{{- $p := . -}}
{{- $eff := mulf $p.effectivePer1M 1000000 | printf "%.0f" -}}
{{- $totalVar := include "ai-models.celToken" "total_tokens" -}}
{{- printf "(%s * %s)" $totalVar $eff -}}
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
{{- $threshold := int (default 128000 $pricing.thresholdTokens) -}}
{{- $standardBranch := include "ai-models.weightedCostBranch" $pricing.standard -}}
{{- $longBranch := include "ai-models.weightedCostBranch" $pricing.longContext -}}
{{- $inVar := include "ai-models.celToken" "input_tokens" -}}
{{- $expr = printf "((%s > %d) ? %s : %s)" $inVar $threshold $longBranch $standardBranch -}}
{{- else if eq $pricing.strategy "flat" -}}
{{- $expr = include "ai-models.flatCostBranch" $pricing.standard -}}
{{- else -}}
{{- fail (printf "Route '%s' has unsupported pricing.strategy '%v'" $routeName $pricing.strategy) -}}
{{- end -}}
{{- printf "((%s > 0) ? %s : 0)" $expr $expr -}}
{{- end -}}

