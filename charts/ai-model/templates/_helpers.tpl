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
ai-model.flatPerRequestCostBranch — render a fixed per-request cost CEL expression.
Used for image-generation models where cost is per image, not per token.
Input: pricing dict with standard.effectivePerRequest in USD.
*/}}
{{- define "ai-model.flatPerRequestCostBranch" -}}
{{- $p := . -}}
{{- /* ⚠️ `%.1f`, NOT `%.0f`. CEL has NO implicit numeric promotion, so a bare
       integer literal here makes the whole expression uncompilable:

         1.0 * 10000     ->  found no matching overload for '_*_'
                             applied to '(double, int)'

       `%.0f` renders 0.0100 * 1e6 as "10000" — an int literal — and the AI
       Gateway controller then fails to convert LLMRequestCosts for the route.
       That failure aborts the ENTIRE Gateway reconcile, not just this route, so
       every gateway config change stalls until it is fixed: new backends never
       reach the ext_proc config and requests 500 with "unknown backend".
       Verified live 2026-07-29 on z-image-turbo-local.

       Note the sibling branches use `%.4f` and are safe by accident; this was
       the only branch that could emit a decimal-less literal. Helm renders it
       happily and `helm lint` cannot see it — CEL is only validated by the
       controller, at sync time. */ -}}
{{- $cost := mulf $p.effectivePerRequest 1000000.0 | printf "%.1f" -}}
{{- printf "1.0 * %s" $cost -}}
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
{{- else if eq $pricing.strategy "flatPerRequest" -}}
{{- $expr = include "ai-model.flatPerRequestCostBranch" $pricing.standard -}}
{{- else -}}
{{- fail (printf "Model '%s' has unsupported pricing.strategy '%v'" $modelName $pricing.strategy) -}}
{{- end -}}
{{- /* Ensure we return an integer and it's non-negative */ -}}
{{- printf "int(%s > 0.0 ? %s : 0.0)" $expr $expr -}}
{{- end -}}
