{{- define "ai-model.priceScale" -}}
{{- printf "%d" (int (round (mulf (default 0 .) 1000) 0)) -}}
{{- end -}}

{{- define "ai-model.weightedCostBranch" -}}
{{- $p := . -}}
{{- $in := mulf $p.inputPer1M 1.0 | printf "%.4f" -}}
{{- $ca := mulf (default 0.0 $p.cachedInputPer1M) 1.0 | printf "%.4f" -}}
{{- $out := mulf $p.outputPer1M 1.0 | printf "%.4f" -}}
{{- printf "(double(input_tokens) - double(cached_input_tokens)) * %s + double(cached_input_tokens) * %s + double(output_tokens) * %s" $in $ca $out -}}
{{- end -}}

{{- define "ai-model.flatCostBranch" -}}
{{- $p := . -}}
{{- $eff := mulf $p.effectivePer1M 1.0 | printf "%.4f" -}}
{{- printf "double(total_tokens) * %s" $eff -}}
{{- end -}}

{{/*
ai-model.costExpression — render the cost CEL expression for a model.
Input: dict { modelName, pricing }
*/}}
{{- define "ai-model.costExpression" -}}
{{- $modelName := .modelName -}}
{{- $pricing := .pricing -}}
{{- if not $pricing -}}
{{- fail (printf "Model '%s' is missing pricing configuration" $modelName) -}}
{{- end -}}
{{- $expr := "" -}}
{{- if eq $pricing.strategy "weighted" -}}
{{- $expr = include "ai-model.weightedCostBranch" $pricing.standard -}}
{{- else if eq $pricing.strategy "tieredWeighted" -}}
{{- if not $pricing.longContext -}}
{{- fail (printf "Model '%s' uses tieredWeighted pricing but is missing pricing.longContext" $modelName) -}}
{{- end -}}
{{- $threshold := int (default 128000 $pricing.thresholdTokens) -}}
{{- $standardBranch := include "ai-model.weightedCostBranch" $pricing.standard -}}
{{- $longBranch := include "ai-model.weightedCostBranch" $pricing.longContext -}}
{{- $expr = printf "(double(input_tokens) > %d.0 ? %s : %s)" $threshold $longBranch $standardBranch -}}
{{- else if eq $pricing.strategy "flat" -}}
{{- $expr = include "ai-model.flatCostBranch" $pricing.standard -}}
{{- else -}}
{{- fail (printf "Model '%s' has unsupported pricing.strategy '%v'" $modelName $pricing.strategy) -}}
{{- end -}}
{{- /* Ensure we return an integer and it's non-negative */ -}}
{{- printf "int(%s > 0.0 ? %s : 0.0)" $expr $expr -}}
{{- end -}}
