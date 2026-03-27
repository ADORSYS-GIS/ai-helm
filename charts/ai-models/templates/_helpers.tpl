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
{{- $in := mulf $p.inputPer1M 1.0 | printf "%.4f" -}}
{{- $ca := mulf (default 0.0 $p.cachedInputPer1M) 1.0 | printf "%.4f" -}}
{{- $out := mulf $p.outputPer1M 1.0 | printf "%.4f" -}}
{{- printf "(double(input_tokens) - double(cached_input_tokens)) * %s + double(cached_input_tokens) * %s + double(output_tokens) * %s" $in $ca $out -}}
{{- end -}}

{{- define "ai-models.flatCostBranch" -}}
{{- $p := . -}}
{{- $eff := mulf $p.effectivePer1M 1.0 | printf "%.4f" -}}
{{- printf "double(total_tokens) * %s" $eff -}}
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
{{- $expr = printf "(double(input_tokens) > %d.0 ? %s : %s)" $threshold $longBranch $standardBranch -}}
{{- else if eq $pricing.strategy "flat" -}}
{{- $expr = include "ai-models.flatCostBranch" $pricing.standard -}}
{{- else -}}
{{- fail (printf "Route '%s' has unsupported pricing.strategy '%v'" $routeName $pricing.strategy) -}}
{{- end -}}
{{- /* Ensure we return an integer and it's non-negative */ -}}
{{- printf "int(%s > 0.0 ? %s : 0.0)" $expr $expr -}}
{{- end -}}





