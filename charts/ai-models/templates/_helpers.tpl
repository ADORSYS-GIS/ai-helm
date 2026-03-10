{{/*
Budget-driven rate limiting helpers.
*/}}
{{- define "ai-models.budgeting.enabled" -}}
{{- .Values.rateLimitBudgeting.enabled | default false -}}
{{- end -}}


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
{{- $plan -}}
{{- end -}}


{{/*
Resolve the pricing profile for a given model.
- .ctx: The top-level chart context (.).
- .model: The model object from the values.
- .modelName: The name of the model.
*/}}
{{- define "ai-models.budgeting.profileForModel" -}}
{{- $ctx := .ctx -}}
{{- $model := .model -}}
{{- $modelName := .modelName -}}
{{- $identifier := $model.identifier | required (printf "Model '%s' is missing required field 'identifier'" $modelName) -}}
{{- $profile := get $ctx.Values.rateLimitBudgeting.pricingProfiles $identifier | required (printf "Pricing profile '%s' for model '%s' not found" $identifier $modelName) -}}
{{- $profile -}}
{{- end -}}


{{/*
---
Calculation Helpers
---
*/}}

{{/*
Calculate the effective price per 1 million tokens for a model profile.
- .profile: The pricing profile for the model.
- .profileName: The name of the profile (for error messages).
*/}}
{{- define "ai-models.budgeting.effectivePer1M" -}}
{{- $profile := .profile -}}
{{- $profileName := .profileName -}}
{{- if not $profile -}}
{{- fail (printf "Pricing profile '%s' is missing or null" $profileName) -}}
{{- end -}}
{{- $mode := $profile.mode | required (printf "Pricing profile '%s' is missing 'mode'" $profileName) -}}

{{- if eq $mode "weighted" -}}
  {{- $inputPer1M := $profile.inputPer1M | required (printf "Weighted profile '%s' is missing 'inputPer1M'" $profileName) -}}
  {{- $outputPer1M := $profile.outputPer1M | required (printf "Weighted profile '%s' is missing 'outputPer1M'" $profileName) -}}
  {{- $avgInputShare := $profile.avgInputShare | required (printf "Weighted profile '%s' is missing 'avgInputShare'" $profileName) -}}
  {{- $avgOutputShare := $profile.avgOutputShare | required (printf "Weighted profile '%s' is missing 'avgOutputShare'" $profileName) -}}
  {{- $shareSum := add (float64 $avgInputShare) (float64 $avgOutputShare) -}}
  {{- if not (eq (printf "%.2f" $shareSum) "1.00") -}}
    {{- fail (printf "Weighted profile '%s' has shares that do not sum to 1.00 (got %.2f)" $profileName $shareSum) -}}
  {{- end -}}
  {{- $effectivePrice := add (mul (float64 $inputPer1M) (float64 $avgInputShare)) (mul (float64 $outputPer1M) (float64 $avgOutputShare)) -}}
  {{- $effectivePrice -}}

{{- else if eq $mode "fixed" -}}
  {{- $effectivePrice := $profile.effectivePer1M | required (printf "Fixed profile '%s' is missing 'effectivePer1M'" $profileName) -}}
  {{- $effectivePrice -}}

{{- else -}}
  {{- fail (printf "Unsupported pricing mode '%s' for profile '%s'" $mode $profileName) -}}
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
{{- $profile := include "ai-models.budgeting.profileForModel" (dict "ctx" $ctx "model" $model "modelName" $modelName) | fromYaml -}}

{{- $monthlyBudget := float64 $plan.monthlyBudgetUsd -}}
{{- $safetyFactor := float64 ($plan.safetyFactor | default 1.0) -}}
{{- $burstMultiplier := float64 ($plan.burstMultiplier | default 1.0) -}}

{{- $usableMonthlyBudget := mul $monthlyBudget $safetyFactor -}}
{{- $dailyBudget := div $usableMonthlyBudget 30.0 -}}
{{- $weeklyBudget := mul $dailyBudget 7.0 -}}

{{- $effectivePer1M := include "ai-models.budgeting.effectivePer1M" (dict "profile" $profile "profileName" $model.identifier) | float64 -}}
{{- if not (gt $effectivePer1M 0) -}}
  {{- fail (printf "Effective price for model '%s' must be positive" $modelName) -}}
{{- end -}}

{{- $tokensPerUsd := div 1000000.0 $effectivePer1M -}}
{{- $dailyTokens := floor (mul $dailyBudget $tokensPerUsd) -}}
{{- $weeklyTokens := floor (mul $weeklyBudget $tokensPerUsd) -}}
{{- $monthlyTokens := floor (mul $usableMonthlyBudget $tokensPerUsd) -}}
{{- $baseTpm := floor (div $dailyTokens 1440.0) -}}
{{- $burstTpm := floor (mul $baseTpm $burstMultiplier) -}}

{{- $limits := dict
      "dailyTokens" $dailyTokens
      "weeklyTokens" $weeklyTokens
      "monthlyTokens" $monthlyTokens
      "baseTpm" $baseTpm
      "burstTpm" $burstTpm
-}}

{{- $avgTokensPerRequest := $profile.avgTokensPerRequest | default $plan.defaultAvgTokensPerRequest -}}
{{- if $avgTokensPerRequest -}}
  {{- $rpmEstimate := floor (div $burstTpm (float64 $avgTokensPerRequest)) -}}
  {{- $_ := set $limits "rpmEstimate" $rpmEstimate -}}
{{- end -}}

{{- $limits | toYaml -}}
{{- end -}}
