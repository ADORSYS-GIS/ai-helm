{{/*
Consistency validation: ensures model.* values are the single source of truth.
Fails helm render if any dependent location drifts.

model.name MUST match:
  1. llmdRouter.router.modelServers.matchLabels.app  (EPP endpoint selector)
  2. modelServing.global.fullnameOverride            (StatefulSet/Service name)
  3. modelServing.defaultPodOptions.labels.app        (pod label EPP selects on)

model.hfRepo and model.storagePath MUST match:
  4. seedJob.hfRepo       (seed Job download repo — bjw subchart cant read parent)
  5. seedJob.storagePath  (seed Job PVC sub-path — same scope limitation)

Helm cannot use Go templates inside values.yaml, so these are kept in sync
by convention + this validation gate, not by templating.

Included from templates/pvc.yaml so it runs on every helm render.
*/}}
{{- define "llm-d.validate" -}}
{{- $name := .Values.model.name -}}
{{- $eppSelector := .Values.llmdRouter.router.modelServers.matchLabels.app -}}
{{- $fullnameOverride := .Values.modelServing.global.fullnameOverride -}}
{{- $podLabel := .Values.modelServing.defaultPodOptions.labels.app -}}

{{- if ne $name $eppSelector -}}
{{- fail (printf "model.name (%q) != llmdRouter.router.modelServers.matchLabels.app (%q) — these must match." $name $eppSelector) -}}
{{- end -}}

{{- if ne $name $fullnameOverride -}}
{{- fail (printf "model.name (%q) != modelServing.global.fullnameOverride (%q) — these must match." $name $fullnameOverride) -}}
{{- end -}}

{{- if ne $name $podLabel -}}
{{- fail (printf "model.name (%q) != modelServing.defaultPodOptions.labels.app (%q) — these must match." $name $podLabel) -}}
{{- end -}}

{{- $hfRepo := .Values.model.hfRepo -}}
{{- $seedHfRepo := .Values.seedJob.hfRepo -}}
{{- if ne $hfRepo $seedHfRepo -}}
{{- fail (printf "model.hfRepo (%q) != seedJob.hfRepo (%q) — these must match. The seed Job lives in the bjw subchart and cant read parent .Values.model.*." $hfRepo $seedHfRepo) -}}
{{- end -}}

{{- $storagePath := .Values.model.storagePath -}}
{{- $seedStoragePath := .Values.seedJob.storagePath -}}
{{- if ne $storagePath $seedStoragePath -}}
{{- fail (printf "model.storagePath (%q) != seedJob.storagePath (%q) — these must match. The seed Job lives in the bjw subchart and cant read parent .Values.model.*." $storagePath $seedStoragePath) -}}
{{- end -}}
{{- end -}}
