{{- define "ai-models.priceScale" -}}
{{- printf "%d" (int (round (mulf (default 0 .) 1000) 0)) -}}
{{- end -}}

{{- define "ai-models.weightedCostBranch" -}}
{{- $pricing := . -}}
{{- $inputScaled := include "ai-models.priceScale" $pricing.inputPer1M -}}
{{- $cachedScaled := include "ai-models.priceScale" (default 0 $pricing.cachedInputPer1M) -}}
{{- $outputScaled := include "ai-models.priceScale" $pricing.outputPer1M -}}
{{- printf "(((int(input_tokens) - int(cached_input_tokens)) > 0) ? (int(input_tokens) - int(cached_input_tokens)) : 0) * %s) + (int(cached_input_tokens) * %s) + (int(output_tokens) * %s))" $inputScaled $cachedScaled $outputScaled -}}
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
Builds the single global model-branching CEL expression for llm_custom_total_cost.

The AI Gateway controller deduplicates llmRequestCosts entries across all
AIGatewayRoute resources by metadataKey, keeping only the first one it
encounters (non-deterministic Go map iteration). The "winning" CEL for
llm_custom_total_cost is therefore a random model's formula, producing
wrong cost telemetry for all other models.

Fix: define llm_custom_total_cost once in a dedicated anchor route whose
CEL branches on the `model` variable (available in the CEL environment).
All individual AIGatewayRoute resources omit the CEL entry entirely.
*/}}
{{- define "ai-models.globalCostCEL" -}}
{{- $models := .Values.models -}}
{{- $first := true -}}
{{- $expr := "" -}}
{{- range $routeName, $routeConfig := $models -}}
  {{- if (default true $routeConfig.enabled) -}}
    {{- $branch := include "ai-models.costExpression" (dict "routeName" $routeName "routeConfig" $routeConfig) -}}
    {{- if $first -}}
      {{- $expr = printf "(model == %q) ? %s" $routeName $branch -}}
      {{- $first = false -}}
    {{- else -}}
      {{- $expr = printf "%s : (model == %q) ? %s" $expr $routeName $branch -}}
    {{- end -}}
  {{- end -}}
{{- end -}}
{{- $expr = printf "%s : 0.0" $expr -}}
{{- $expr -}}
{{- end -}}