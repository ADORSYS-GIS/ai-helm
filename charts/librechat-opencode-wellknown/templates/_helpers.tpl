{{- /*
wellknown.tokenIssue — "empty" | "whitespace" | "" for a string used verbatim as a
reasoning effort (the host sends it as `reasoning_effort` untouched).
*/ -}}
{{- define "wellknown.tokenIssue" -}}
{{- if eq (trim .) "" -}}empty{{- else if ne (trim .) . -}}whitespace{{- end -}}
{{- end -}}

{{- /*
wellknown.reasoning — the ONE place the catalog's reasoning keys are validated
and normalised (ADR-0143). Both well-known documents (v2 `opencode`, and the
temporary v1 bridge `opencode-v1`) consume its output; the validation is shared,
the two rendering loops in configmap.yaml are separate code kept in step by
tests/opencode-wellknown-reasoning/run.sh.

Input : .Values.models  (modelName -> cfg, injected by the ai-models orchestrator)
Output: JSON object  { "<model>": { "effort": "<default>", "levels": ["<level>", ...] } }
        Only models carrying `reasoningEffort` appear; `levels` is [] when the
        model has no `reasoningLevels`. Decode with `fromJson`.

Every problem across ALL models is collected (models in name order) and the
render `fail`s ONCE with a count header and one line per problem, each starting
`models.<name>: ` — ArgoCD surfaces only that one message, so reporting just the
first bad model would turn a 28-model stale catalog into 28 sync round trips.
The previously synced ConfigMap keeps being served.
*/ -}}
{{- define "wellknown.reasoning" -}}
{{- $out := dict -}}
{{- $problems := list -}}
{{- $models := . -}}
{{- /* Explicit name order: the failure lists problems sorted by model. */ -}}
{{- range $name := (keys $models | sortAlpha) -}}
  {{- $cfg := index $models $name -}}
  {{- /* `some-model: null` (or any non-map) carries no reasoning keys: skip. */ -}}
  {{- if kindIs "map" $cfg -}}
    {{- if hasKey $cfg "reasoningEffortHigh" -}}
      {{- $problems = append $problems (printf "models.%s: `reasoningEffortHigh` was removed (ADR-0143); replace it with `reasoningLevels: [...]`, the effort levels the client menu offers (e.g. [none, low, high]), and keep `reasoningEffort` as the default. The catalog is stale." $name) -}}
    {{- end -}}
    {{- $hasEffort := hasKey $cfg "reasoningEffort" -}}
    {{- $hasLevels := hasKey $cfg "reasoningLevels" -}}
    {{- if and $hasLevels (not $hasEffort) -}}
      {{- $problems = append $problems (printf "models.%s: `reasoningLevels` is set but `reasoningEffort` is not; add `reasoningEffort: <default level>` (the entry the client menu calls \"Default\"), or remove `reasoningLevels`." $name) -}}
    {{- end -}}
    {{- $effort := "" -}}
    {{- $effortOk := false -}}
    {{- if $hasEffort -}}
      {{- $effort = $cfg.reasoningEffort -}}
      {{- if kindIs "invalid" $effort -}}
        {{- $problems = append $problems (printf "models.%s: `reasoningEffort` is null; set the default effort as a non-empty string, or remove the key." $name) -}}
      {{- else if not (kindIs "string" $effort) -}}
        {{- $problems = append $problems (printf "models.%s: `reasoningEffort` must be a string, got %s %q. YAML 1.1 turns unquoted off/on/yes/no into booleans and 50 into a number: quote it (reasoningEffort: \"off\")." $name (kindOf $effort) (printf "%v" $effort)) -}}
      {{- else if eq (include "wellknown.tokenIssue" $effort) "empty" -}}
        {{- $problems = append $problems (printf "models.%s: `reasoningEffort` is empty (%q); set the default effort or remove the key." $name $effort) -}}
      {{- else if eq (include "wellknown.tokenIssue" $effort) "whitespace" -}}
        {{- $problems = append $problems (printf "models.%s: `reasoningEffort` %q has leading/trailing whitespace; the host sends it verbatim, remove the spaces." $name $effort) -}}
      {{- else -}}
        {{- $effortOk = true -}}
      {{- end -}}
    {{- end -}}
    {{- $levels := list -}}
    {{- if $hasLevels -}}
      {{- $raw := $cfg.reasoningLevels -}}
      {{- if kindIs "invalid" $raw -}}
        {{- $problems = append $problems (printf "models.%s: `reasoningLevels` is null; list the selectable levels (e.g. [none, low, high]), or remove the key to offer none." $name) -}}
      {{- else if not (kindIs "slice" $raw) -}}
        {{- $problems = append $problems (printf "models.%s: `reasoningLevels` must be a list of strings, got %s. Write `reasoningLevels: [none, low, high]`." $name (kindOf $raw)) -}}
      {{- else if eq (len $raw) 0 -}}
        {{- $problems = append $problems (printf "models.%s: `reasoningLevels` is an empty list; to offer no extra levels, remove the key." $name) -}}
      {{- else -}}
        {{- /* Case-insensitive duplicate detection (High == high: one menu entry to a
               human, one level to a backend); the EMITTED value is never lowercased. */ -}}
        {{- $seen := dict -}}
        {{- range $i, $lvl := $raw -}}
          {{- if kindIs "invalid" $lvl -}}
            {{- $problems = append $problems (printf "models.%s: `reasoningLevels[%d]` is null; quote every level, and remove empty list items." $name $i) -}}
          {{- else if not (kindIs "string" $lvl) -}}
            {{- $problems = append $problems (printf "models.%s: `reasoningLevels[%d]` must be a string, got %s %q. Quote the entry: YAML 1.1 turns unquoted off/on/yes/no into booleans and 50 into a number (use \"off\", not off)." $name $i (kindOf $lvl) (printf "%v" $lvl)) -}}
          {{- else if eq (include "wellknown.tokenIssue" $lvl) "empty" -}}
            {{- $problems = append $problems (printf "models.%s: `reasoningLevels[%d]` is empty (%q); remove it or give it a name." $name $i $lvl) -}}
          {{- else if eq (include "wellknown.tokenIssue" $lvl) "whitespace" -}}
            {{- $problems = append $problems (printf "models.%s: `reasoningLevels[%d]` %q has leading/trailing whitespace; the host sends it verbatim, remove the spaces." $name $i $lvl) -}}
          {{- else if hasKey $seen (lower $lvl) -}}
            {{- $problems = append $problems (printf "models.%s: `reasoningLevels` lists %q more than once (it repeats %q, compared case-insensitively); each level is one client menu entry, so it must be unique." $name $lvl (index $seen (lower $lvl))) -}}
          {{- else -}}
            {{- $_ := set $seen (lower $lvl) $lvl -}}
            {{- $levels = append $levels $lvl -}}
          {{- end -}}
        {{- end -}}
      {{- end -}}
    {{- end -}}
    {{- if and $hasEffort $effortOk -}}
      {{- $_ := set $out $name (dict "effort" $effort "levels" $levels) -}}
    {{- end -}}
  {{- end -}}
{{- end -}}
{{- if $problems -}}
  {{- fail (printf "invalid reasoning settings in the models catalog: %d problem(s) (ADR-0143)\n%s" (len $problems) (join "\n" $problems)) -}}
{{- end -}}
{{- $out | toJson -}}
{{- end -}}
