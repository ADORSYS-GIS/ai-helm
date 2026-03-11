{{/*
Budget-driven rate limiting helpers.
*/}}


{{/*
---
Validation Helpers
---
*/}}

{{/*
Validate a plan configuration.
- .plan: The plan object to validate.
- .name: The name of the plan.
*/}}
{{- define "ai-models.budgeting.validatePlan" -}}
{{- $plan := .plan -}}
{{- $name := .name -}}
{{- if not $plan -}}
{{- fail (printf "Plan '%s' is not defined in .Values.rateLimitBudgeting.plans" $name) -}}
{{- end -}}
{{- $monthlyBudget := $plan.monthlyBudgetUsd | required (printf "Plan '%s' is missing required field 'monthlyBudgetUsd'" $name) -}}
{{- if not (or (kindIs "numeric" $monthlyBudget) (kindIs "int64" $monthlyBudget) (kindIs "float64" $monthlyBudget) (kindIs "int" $monthlyBudget)) -}}
{{- fail (printf "Plan '%s' has a non-numeric 'monthlyBudgetUsd'" $name) -}}
{{- end -}}
{{- if not (gt (float64 $monthlyBudget) 0.0) -}}
{{- fail (printf "Plan '%s' has a non-positive 'monthlyBudgetUsd'" $name) -}}
{{- end -}}
{{- $safetyFactor := $plan.safetyFactor | default 1.0 -}}
{{- if not (or (kindIs "numeric" $safetyFactor) (kindIs "float64" $safetyFactor) (kindIs "int64" $safetyFactor) (kindIs "int" $safetyFactor)) -}}
{{- fail (printf "Plan '%s' has a non-numeric 'safetyFactor'" $name) -}}
{{- end -}}
{{- if not (and (gt (float64 $safetyFactor) 0.0) (le (float64 $safetyFactor) 1.0)) -}}
{{- fail (printf "Plan '%s' has a 'safetyFactor' outside the range (0, 1]" $name) -}}
{{- end -}}
{{- $burstMultiplier := $plan.burstMultiplier | default 1.0 -}}
{{- if not (or (kindIs "numeric" $burstMultiplier) (kindIs "float64" $burstMultiplier) (kindIs "int64" $burstMultiplier) (kindIs "int" $burstMultiplier)) -}}
{{- fail (printf "Plan '%s' has a non-numeric 'burstMultiplier'" $name) -}}
{{- end -}}
{{- if not (ge (float64 $burstMultiplier) 1.0) -}}
{{- fail (printf "Plan '%s' has a 'burstMultiplier' less than 1" $name) -}}
{{- end -}}
{{- $effectiveMinutes := $plan.effectiveMinutes | default 1440.0 -}}
{{- if not (or (kindIs "numeric" $effectiveMinutes) (kindIs "float64" $effectiveMinutes) (kindIs "int64" $effectiveMinutes) (kindIs "int" $effectiveMinutes)) -}}
{{- fail (printf "Plan '%s' has a non-numeric 'effectiveMinutes'" $name) -}}
{{- end -}}
{{- $tokenVarianceMultiplier := $plan.tokenVarianceMultiplier | default 1.0 -}}
{{- if not (or (kindIs "numeric" $tokenVarianceMultiplier) (kindIs "float64" $tokenVarianceMultiplier) (kindIs "int64" $tokenVarianceMultiplier) (kindIs "int" $tokenVarianceMultiplier)) -}}
{{- fail (printf "Plan '%s' has a non-numeric 'tokenVarianceMultiplier'" $name) -}}
{{- end -}}
{{- $avgTokensPerSecondPerRequest := $plan.avgTokensPerSecondPerRequest | default 1.0 -}}
{{- if not (or (kindIs "numeric" $avgTokensPerSecondPerRequest) (kindIs "float64" $avgTokensPerSecondPerRequest) (kindIs "int64" $avgTokensPerSecondPerRequest) (kindIs "int" $avgTokensPerSecondPerRequest)) -}}
{{- fail (printf "Plan '%s' has a non-numeric 'avgTokensPerSecondPerRequest'" $name) -}}
{{- end -}}
{{- end -}}


{{/*
Resolve and validate the currently selected plan.
- .ctx: The top-level chart context (.).
*/}}
{{- define "ai-models.budgeting.plan" -}}
{{- $ctx := .ctx -}}
{{- $planName := $ctx.Values.rateLimitBudgeting.defaultPlan | required "rateLimitBudgeting.defaultPlan is not set" -}}
{{- $plan := get $ctx.Values.rateLimitBudgeting.plans $planName -}}
{{- $validationScope := dict "plan" $plan "name" $planName -}}
{{- include "ai-models.budgeting.validatePlan" $validationScope -}}
{{- $plan | toYaml -}}
{{- end -}}


{{/*
---
Calculation Helpers
---
*/}}

{{/*
Calculate the effective price per 1 million tokens for a model.
- .model: The model object (directly containing pricing info).
- .modelName: The name of the model (for error messages).
- .avgTokensPerRequest: The average tokens per request.
- .safeAvgTokensPerRequest: The safe average tokens per request.
*/}}
{{- define "ai-models.budgeting.effectivePer1M" -}}
{{- $model := .model -}}
{{- $modelName := .modelName -}}
{{- $avgTokensPerRequest := .avgTokensPerRequest -}}
{{- $safeAvgTokensPerRequest := .safeAvgTokensPerRequest -}}
{{- if not $model -}}
{{- fail (printf "Model '%s' is missing or null" $modelName) -}}
{{- end -}}
{{- $mode := $model.mode | required (printf "Model '%s' is missing pricing 'mode'" $modelName) -}}

{{- if eq $mode "weighted" -}}
  {{- $inputPer1M := $model.inputPer1M | required (printf "Weighted model '%s' is missing 'inputPer1M'" $modelName) -}}
  {{- $outputPer1M := $model.outputPer1M | required (printf "Weighted model '%s' is missing 'outputPer1M'" $modelName) -}}
  {{- $avgInputShare := $model.avgInputShare | required (printf "Weighted model '%s' is missing 'avgInputShare'" $modelName) -}}
  {{- $avgOutputShare := $model.avgOutputShare | required (printf "Weighted model '%s' is missing 'avgOutputShare'" $modelName) -}}
  {{- $shareSum := addf (float64 $avgInputShare) (float64 $avgOutputShare) -}}
  {{- if or (lt $shareSum 0.999) (gt $shareSum 1.001) -}}
    {{- fail (printf "Weighted model '%s' has shares that do not sum to 1.00 (got %.4f)" $modelName $shareSum) -}}
  {{- end -}}
  {{- $avgInputTokens := mulf (float64 $avgTokensPerRequest) (float64 $avgInputShare) -}}
  {{- $avgOutputTokens := mulf (float64 $avgTokensPerRequest) (float64 $avgOutputShare) -}}
  {{- $avgRequestCost := addf (divf (mulf $avgInputTokens (float64 $inputPer1M)) 1000000.0) (divf (mulf $avgOutputTokens (float64 $outputPer1M)) 1000000.0) -}}
  {{- $effectivePrice := mulf (divf $avgRequestCost (float64 $safeAvgTokensPerRequest)) 1000000.0 -}}
  {{- $effectivePrice -}}

{{- else if eq $mode "fixed" -}}
  {{- $baseEffectivePrice := $model.effectivePer1M | required (printf "Fixed model '%s' is missing 'effectivePer1M'" $modelName) -}}
  {{- $avgRequestCost := divf (mulf (float64 $avgTokensPerRequest) (float64 $baseEffectivePrice)) 1000000.0 -}}
  {{- $effectivePrice := mulf (divf $avgRequestCost (float64 $safeAvgTokensPerRequest)) 1000000.0 -}}
  {{- $effectivePrice -}}

{{- else -}}
  {{- fail (printf "Unsupported pricing mode '%s' for model '%s'" $mode $modelName) -}}
{{- end -}}
{{- end -}}


{{/*
Compute derived rate limits for a model based on a plan.
- .ctx: The top-level chart context (.).
- .model: The model object from the values.
- .modelName: The name of the model.
*/}}
{{- define "ai-models.budgeting.derivedLimits" -}}
{{- $ctx := .ctx -}}
{{- $model := .model -}}
{{- $modelName := .modelName -}}

{{- $plan := include "ai-models.budgeting.plan" (dict "ctx" $ctx) | fromYaml -}}

{{- $monthlyBudget := float64 $plan.monthlyBudgetUsd -}}
{{- $safetyFactor := float64 ($plan.safetyFactor | default 1.0) -}}
{{- $burstMultiplier := float64 ($plan.burstMultiplier | default 1.0) -}}
{{- $effectiveMinutes := float64 ($plan.effectiveMinutes | default 1440.0) -}}
{{- $tokenVarianceMultiplier := float64 ($plan.tokenVarianceMultiplier | default 1.0) -}}
{{- $avgTokensPerSecondPerRequest := float64 ($plan.avgTokensPerSecondPerRequest | default 1.0) -}}

{{- $usableMonthlyBudget := mulf $monthlyBudget $safetyFactor -}}
{{- $dailyBudget := divf $usableMonthlyBudget 20.0 -}}
{{- $weeklyBudget := mulf $dailyBudget 7.0 -}}

{{- $avgTokensPerRequest := float64 ($model.avgTokensPerRequest | default $plan.defaultAvgTokensPerRequest | default 1000) -}}
{{- $safeAvgTokensPerRequest := floor (mulf $avgTokensPerRequest $tokenVarianceMultiplier) -}}

{{- $effectivePer1M := include "ai-models.budgeting.effectivePer1M" (dict "model" $model "modelName" $modelName "avgTokensPerRequest" $avgTokensPerRequest "safeAvgTokensPerRequest" $safeAvgTokensPerRequest) | float64 -}}
{{- if not (gt $effectivePer1M 0.0) -}}
  {{- fail (printf "Effective price for model '%s' must be positive" $modelName) -}}
{{- end -}}

{{- $tokensPerUsd := divf 1000000.0 $effectivePer1M -}}
{{- $dailyTokens := floor (mulf $dailyBudget $tokensPerUsd) | int64 -}}
{{- $weeklyTokens := floor (mulf $weeklyBudget $tokensPerUsd) | int64 -}}
{{- $monthlyTokens := floor (mulf $usableMonthlyBudget $tokensPerUsd) | int64 -}}
{{- $baseTpm := floor (divf (float64 $dailyTokens) $effectiveMinutes) | int64 -}}
{{- $burstTpm := floor (mulf (float64 $baseTpm) $burstMultiplier) | int64 -}}

{{- $baseRpm := floor (divf (float64 $baseTpm) $safeAvgTokensPerRequest) | int64 -}}
{{- $burstRpm := floor (divf (float64 $burstTpm) $safeAvgTokensPerRequest) | int64 -}}
{{- $maxConcurrentRequests := floor (divf (float64 $burstTpm) $avgTokensPerSecondPerRequest) | int64 -}}

{{- $limits := dict
      "dailyTokens" $dailyTokens
      "weeklyTokens" $weeklyTokens
      "monthlyTokens" $monthlyTokens
      "baseTpm" $baseTpm
      "burstTpm" $burstTpm
      "baseRpm" $baseRpm
      "burstRpm" $burstRpm
      "maxConcurrentRequests" $maxConcurrentRequests
-}}

{{- $limits | toYaml -}}
{{- end -}}
