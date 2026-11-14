#!/usr/bin/env zsh
# Behaviour tests for the catalog-derived reasoning levels in
# charts/librechat-opencode-wellknown (ADR-0143).
#
# Renders the chart and asserts on the PARSED JSON of both ConfigMap documents
# (`opencode` = OpenCode v2, `opencode-v1` = temporary v1 bridge), then proves every
# render-time guard by feeding it a bad catalog and requiring `helm template` to fail
# loudly, naming the model and the offending key.
#
#   ./tests/opencode-wellknown-reasoning/run.sh      (needs helm, yq v4, python3)
#
# No cluster, no Docker, no network once the chart dependencies are vendored.
set -u

HERE="${0:a:h}"
ROOT="${HERE:h:h}"
CHART="$ROOT/charts/librechat-opencode-wellknown"
FIXTURE="$CHART/ci/reasoning-values.yaml"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0
ok()  { printf 'PASS  %s\n' "$1"; ((pass++)) }
bad() { printf 'FAIL  %s\n' "$1"; ((fail++)) }

if [[ ! -d "$CHART/charts" ]]; then
  helm dependency update "$CHART" >/dev/null || { echo "helm dependency update failed"; exit 1 }
fi

# render <values-file> <out-prefix>: writes <out-prefix>.v2.json and <out-prefix>.v1.json
render() {
  local values="$1" prefix="$2" rendered
  rendered="$(helm template wk "$CHART" -f "$values" -s templates/configmap.yaml 2>"$prefix.err")" || return 1
  print -r -- "$rendered" | yq 'select(.metadata.name == "wk-content") | .data.opencode' >"$prefix.v2.json" || return 1
  print -r -- "$rendered" | yq 'select(.metadata.name == "wk-content") | .data."opencode-v1"' >"$prefix.v1.json" || return 1
}

# ── positive: fixture render ────────────────────────────────────────────────
echo "── positive: parsed JSON of both documents ───────────────────────────────────"
print -r -- 'models: {}' >"$TMP/empty.yaml"
render "$TMP/empty.yaml" "$TMP/base" || { echo "baseline render failed"; cat "$TMP/base.err"; exit 1 }
render "$FIXTURE" "$TMP/fx" || { echo "fixture render failed"; cat "$TMP/fx.err"; exit 1 }

pyout="$(python3 - "$TMP/fx" "$TMP/base" <<'PY'
import json, sys

fx, base = sys.argv[1], sys.argv[2]
failures = 0

def check(name, cond, detail=""):
    global failures
    if cond:
        print(f"PASS  {name}")
    else:
        failures += 1
        print(f"FAIL  {name}  {detail}")

def load(prefix, which):
    with open(f"{prefix}.{which}.json") as f:
        return json.load(f)

v2, v1 = load(fx, "v2"), load(fx, "v1")
v2b, v1b = load(base, "v2"), load(base, "v1")
m2 = v2["config"]["providers"]["camer-digital"]["models"]
m1 = v1["config"]["provider"]["camer-digital"]["models"]

check("v2: models are exactly the two capped fixture models",
      sorted(m2) == ["ci-default-only", "ci-levels"], sorted(m2))
check("v1: models are exactly the two capped fixture models",
      sorted(m1) == ["ci-default-only", "ci-levels"], sorted(m1))
check("v2: uncapped model absent", "ci-uncapped" not in m2)
check("v1: uncapped model absent", "ci-uncapped" not in m1)

levels = ["none", "low", "high", "max"]
check("v2: variants is a LIST, one entry per level, catalog order preserved",
      m2["ci-levels"].get("variants") == [{"id": l, "settings": {"reasoningEffort": l}} for l in levels],
      m2["ci-levels"].get("variants"))
check("v2: default effort stays in settings",
      m2["ci-levels"].get("settings") == {"reasoningEffort": "low"}, m2["ci-levels"].get("settings"))
check("v1: variants is a MAP, one entry per level",
      m1["ci-levels"].get("variants") == {l: {"reasoningEffort": l} for l in levels},
      m1["ci-levels"].get("variants"))
check("v1: default effort stays in options",
      m1["ci-levels"].get("options") == {"reasoningEffort": "low"}, m1["ci-levels"].get("options"))
check("v1 and v2 offer the same level set",
      {v["id"] for v in m2["ci-levels"]["variants"]} == set(m1["ci-levels"]["variants"]))
check("v2: default level 'low' is not de-duplicated away (listed levels are exactly the menu)",
      "low" in [v["id"] for v in m2["ci-levels"]["variants"]])
check("v2: no 'thinking' variant id any more",
      "thinking" not in [v["id"] for v in m2["ci-levels"]["variants"]])

check("v2: default-only model has settings and NO variants key",
      m2["ci-default-only"] == {"settings": {"reasoningEffort": "medium"}}, m2["ci-default-only"])
check("v1: default-only model has options and NO variants key",
      m1["ci-default-only"] == {"options": {"reasoningEffort": "medium"}}, m1["ci-default-only"])

# Nothing outside providers.camer-digital.models may change vs. a render with `models: {}`.
check("baseline (models: {}) has no models key in v2",
      "models" not in v2b["config"]["providers"]["camer-digital"])
check("baseline (models: {}) has no models key in v1",
      "models" not in v1b["config"]["provider"]["camer-digital"])
del v2["config"]["providers"]["camer-digital"]["models"]
del v1["config"]["provider"]["camer-digital"]["models"]
check("v2: everything outside providers.camer-digital.models is identical to the baseline",
      v2 == v2b)
check("v1: everything outside provider.camer-digital.models is identical to the baseline",
      v1 == v1b)

sys.exit(1 if failures else 0)
PY
)"
pyrc=$?
print -r -- "$pyout"
(( pyrc == 0 )) || bad "assertion script exited $pyrc"
pass=$(( pass + $(print -r -- "$pyout" | grep -c '^PASS') ))
fail=$(( fail + $(print -r -- "$pyout" | grep -c '^FAIL') ))

# ── positive: null / non-map model entry and an all-uncapped catalog ────────
echo "── positive: null model cfg, no reasoning keys anywhere ──────────────────────"
cat >"$TMP/null.yaml" <<'YAML'
models:
  null-cfg-model: null
  string-cfg-model: reasoningEffort
  list-cfg-model: [reasoningEffort, high]
  number-cfg-model: 5
  plain-model:
    kind: text
YAML
if render "$TMP/null.yaml" "$TMP/null"; then
  if python3 - "$TMP/null" "$TMP/base" <<'PY'
import json, sys
a, b = sys.argv[1], sys.argv[2]
for w in ("v2", "v1"):
    if json.load(open(f"{a}.{w}.json")) != json.load(open(f"{b}.{w}.json")):
        sys.exit(1)
PY
  then ok "null/string/list/number model entries are skipped; no capped model => provider gets no models key (both documents identical to baseline)"
  else bad "non-map model entries / all-uncapped catalog changed the rendered documents"; fi
else
  bad "non-map model entries crashed the render: $(<"$TMP/null.err")"
fi

# ── positive: the case of a level is emitted verbatim (only the duplicate check folds case)
echo "── positive: mixed-case levels are emitted as written ────────────────────────"
cat >"$TMP/case.yaml" <<'YAML'
models:
  case-model:
    reasoningEffort: Medium
    reasoningLevels: [None, High, Max]
YAML
if render "$TMP/case.yaml" "$TMP/case" && python3 - "$TMP/case" <<'PY'
import json, sys
p = sys.argv[1]
v2 = json.load(open(p + ".v2.json"))["config"]["providers"]["camer-digital"]["models"]["case-model"]
v1 = json.load(open(p + ".v1.json"))["config"]["provider"]["camer-digital"]["models"]["case-model"]
want = ["None", "High", "Max"]
assert v2["settings"] == {"reasoningEffort": "Medium"}, v2
assert [v["id"] for v in v2["variants"]] == want, v2
assert [v["settings"]["reasoningEffort"] for v in v2["variants"]] == want, v2
assert sorted(v1["variants"]) == sorted(want), v1
assert v1["options"] == {"reasoningEffort": "Medium"}, v1
PY
then ok "mixed-case default and levels are emitted verbatim in both documents"
else bad "mixed-case levels were altered or the render failed"; fi

# ── negative: every guard fails loudly, naming the model and the key ────────
echo "── negative: render-time guards ──────────────────────────────────────────────"
# neg <case name> <key the message must name> <yaml body of model `bad`> [wording fragment]
neg() {
  local name="$1" key="$2" body="$3" want="${4:-}" err rc f
  f="$TMP/neg-${${name// /-}//[^A-Za-z0-9-]/_}.yaml"
  { print -r -- 'models:'; print -r -- '  bad-model:'; print -r -- "$body" | sed 's/^/    /' } >"$f"
  err="$(helm template wk "$CHART" -f "$f" -s templates/configmap.yaml 2>&1 >/dev/null)"; rc=$?
  if (( rc == 0 )); then
    bad "$name: helm template succeeded but must fail"
  elif [[ "$err" != *"models.bad-model"* ]]; then
    bad "$name: failed, but the message does not name the model: $err"
  elif [[ "$err" != *"\`$key\`"* ]]; then
    bad "$name: failed, but the message does not name \`$key\`: $err"
  elif [[ -n "$want" && "$err" != *"$want"* ]]; then
    bad "$name: failed, but the message lacks the wording \"$want\": $err"
  else
    ok "$name -> render fails, names models.bad-model and \`$key\`${want:+ ($want)}"
  fi
}

# negm <case name> <full yaml> <fragments...>: render must fail; a fragment starting with
# "+" must appear in the (single) failure, one starting with "-" must NOT; "<a" "<b" pairs
# (written "@A|B") require A to appear before B.
negm() {
  local name="$1" body="$2" f err rc frag ok_=1; shift 2
  f="$TMP/negm-$RANDOM.yaml"; print -r -- "$body" >"$f"
  err="$(helm template wk "$CHART" -f "$f" -s templates/configmap.yaml 2>&1 >/dev/null)"; rc=$?
  if (( rc == 0 )); then bad "$name: helm template succeeded but must fail"; return; fi
  for frag in "$@"; do
    case "$frag" in
      +*) [[ "$err" == *"${frag#+}"* ]] || { bad "$name: failure lacks \"${frag#+}\": $err"; ok_=0 } ;;
      -*) [[ "$err" != *"${frag#-}"* ]] || { bad "$name: failure names \"${frag#-}\" but must not: $err"; ok_=0 } ;;
      @*) local first="${${frag#@}%%|*}" second="${${frag#@}#*|}"
          local before="${err%%$first*}" after="${err%%$second*}"
          (( ${#before} < ${#after} )) && [[ "$err" == *"$first"* && "$err" == *"$second"* ]] \
            || { bad "$name: \"$first\" must come before \"$second\": $err"; ok_=0 } ;;
    esac
  done
  (( ok_ )) && ok "$name -> one failure, fragments ok: $*"
}

neg "stale reasoningEffortHigh" reasoningEffortHigh $'reasoningEffort: low\nreasoningEffortHigh: high'
neg "stale reasoningEffortHigh empty string" reasoningEffortHigh $'reasoningEffort: low\nreasoningEffortHigh: ""'
neg "stale reasoningEffortHigh alone" reasoningEffortHigh 'reasoningEffortHigh: high'
neg "levels without default" reasoningLevels 'reasoningLevels: [low, high]'
neg "default off (YAML boolean)" reasoningEffort 'reasoningEffort: off'
neg "default no (YAML boolean)" reasoningEffort 'reasoningEffort: no'
neg "default number" reasoningEffort 'reasoningEffort: 50'
neg "default empty string" reasoningEffort 'reasoningEffort: ""'
neg "levels is a string" reasoningLevels $'reasoningEffort: low\nreasoningLevels: high'
neg "levels is a map" reasoningLevels $'reasoningEffort: low\nreasoningLevels: {a: b}'
neg "levels empty list" reasoningLevels $'reasoningEffort: low\nreasoningLevels: []'
neg "levels entry off" 'reasoningLevels[1]' $'reasoningEffort: low\nreasoningLevels: [low, off]'
neg "levels entry on" 'reasoningLevels[0]' $'reasoningEffort: low\nreasoningLevels: [on, high]'
neg "levels entry yes" 'reasoningLevels[0]' $'reasoningEffort: low\nreasoningLevels: [yes]'
neg "levels entry number" 'reasoningLevels[0]' $'reasoningEffort: low\nreasoningLevels: [50]'
neg "levels entry null" 'reasoningLevels[1]' $'reasoningEffort: low\nreasoningLevels: [low, null]'
neg "levels entry empty string" 'reasoningLevels[0]' $'reasoningEffort: low\nreasoningLevels: [""]'
neg "levels duplicate" reasoningLevels $'reasoningEffort: low\nreasoningLevels: [low, high, low]' '"low" more than once'
neg "levels duplicate differing only by case" reasoningLevels $'reasoningEffort: low\nreasoningLevels: [high, High]' '"High" more than once (it repeats "high"'
neg "default whitespace-only" reasoningEffort 'reasoningEffort: " "' 'is empty'
neg "default with surrounding whitespace" reasoningEffort 'reasoningEffort: " low"' 'has leading/trailing whitespace'
neg "level whitespace-only" 'reasoningLevels[1]' $'reasoningEffort: low\nreasoningLevels: [low, "   "]' 'is empty'
neg "level with surrounding whitespace" 'reasoningLevels[0]' $'reasoningEffort: low\nreasoningLevels: ["high "]' 'has leading/trailing whitespace'
neg "default null with levels" reasoningEffort $'reasoningEffort: null\nreasoningLevels: [low]' 'is null'
neg "levels null" reasoningLevels $'reasoningEffort: low\nreasoningLevels: null' 'is null'
neg "level entry null wording" 'reasoningLevels[1]' $'reasoningEffort: low\nreasoningLevels: [low, null]' 'is null'

echo "── negative: attribution and all-problems-at-once ────────────────────────────"
negm "bad model between good ones" $'models:\n  aaa-good:\n    reasoningEffort: low\n    reasoningLevels: [none, high]\n  mmm-bad:\n    reasoningEffort: off\n  zzz-good:\n    reasoningEffort: high' \
  '+models.mmm-bad' '+`reasoningEffort`' '-models.aaa-good' '-models.zzz-good' '+1 problem(s)'
negm "two bad models reported in one failure, sorted by model" $'models:\n  zulu-bad:\n    reasoningEffort: low\n    reasoningEffortHigh: high\n  alpha-bad:\n    reasoningEffort: low\n    reasoningLevels: [low, low]\n  fine:\n    reasoningEffort: low' \
  '+models.alpha-bad' '+models.zulu-bad' '-models.fine' '+2 problem(s)' '@models.alpha-bad|models.zulu-bad' '+`reasoningLevels`' '+`reasoningEffortHigh`'
negm "several problems on one model are all listed" $'models:\n  m:\n    reasoningEffort: null\n    reasoningLevels: ["ok", "  "]' \
  '+2 problem(s)' '+`reasoningEffort` is null' '+`reasoningLevels[1]` is empty'

echo
printf 'passed=%d failed=%d\n' "$pass" "$fail"
(( fail == 0 ))
