#!/usr/bin/env zsh
# Behaviour tests for the Dynamic Budget Limiter's enforcement filter
# (lightbridge-authz ADR-0034, lightbridge-authz#658).
#
# Drives charts/core-gateway/files/budget-limiter.lua -- byte-for-byte the script the
# EnvoyExtensionPolicy embeds -- through a real Envoy, on the exact image the prod gateway data
# plane runs. 200 means the request reached the upstream; 402 means the account is out of budget;
# 503 means the balance could not be determined, which is emphatically NOT the same answer.
#
#   ./tests/budget-limiter/run.sh          (needs docker, curl, python3 + pyyaml, helm)
#
# Ports 10100-10104 must be free. The container is removed on exit.
#
# STEP 0 IS NOT OPTIONAL. Everything below this line is a DATA-plane test: it proves what the
# script does once Envoy is running it. On 2026-09-03 all 18 of them passed and the filter still
# took the gateway down, because Envoy Gateway's CONTROLLER refused the script before any Envoy
# ever saw it and rewrote every route to `directResponse: 500`
# (ai-helm-values#367 / #368). tests/envoy-gateway-lua/ is the half this file could not see.
#
# THE ACCESS LOG IS UNDER TEST TOO. Every listener logs through the chart's OWN access-log format
# (render-envoy-config.py lifts `format.json` + `matches` out of `helm template` with the limiter
# on), so the four `budget.*` fields ai-helm#1097 added -- the only observable shadow mode has --
# are asserted per request, and so is `response_code_details`. That last field is how the
# 2026-09-03 rows were read: a refusal made INSIDE this filter is always `lua_response`; a request
# it lets through is `via_upstream`; `direct_response` is Envoy's router serving a route with no
# upstream at all, which is what Envoy Gateway substitutes when it refuses a policy. No path
# through this script can produce it, and the last section proves that over every row logged.
set -u

HERE="${0:a:h}"
IMAGE="envoyproxy/envoy:distroless-v1.38.3"
CONTAINER="budget-limiter-envoy-test"

cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true }
trap cleanup EXIT

"$HERE/../envoy-gateway-lua/run.sh" || exit 1
echo

python3 "$HERE/render-envoy-config.py" || exit 1
cleanup
# --file-flush-interval-msec: Envoy's file access logger flushes every 10 s by default, which is
# far longer than this whole run. 50 ms keeps the row assertions below from racing the buffer.
docker run -d --name "$CONTAINER" \
  -p 10100:10100 -p 10101:10101 -p 10102:10102 -p 10103:10103 -p 10104:10104 \
  -v "$HERE/envoy.yaml:/etc/envoy/envoy.yaml:ro" \
  "$IMAGE" -c /etc/envoy/envoy.yaml --log-level warn --file-flush-interval-msec 50 >/dev/null || exit 1

for _ in {1..30}; do
  curl -s -o /dev/null "http://127.0.0.1:10100/" && break
  sleep 1
done

pass=0
fail=0
seq=0
LAST_RID=""
LAST_NAME=""

# `x-test-budget` is consumed by the harness's fake-Authorino filter (see
# render-envoy-config.py) and turned into the ext_authz dynamic metadata the real filter reads.
# Omitting it means "the AuthConfig published nothing at all".
#
# Every request carries a unique x-request-id (the HCM preserves it) so `field` below can find
# its access-log row.
check() {
  local name="$1" expect="$2" port="$3"; shift 3
  local got
  LAST_RID="t$((++seq))"
  LAST_NAME="$name"
  got=$(curl -s -o /dev/null -w '%{http_code}' -H "x-request-id: $LAST_RID" \
    "http://127.0.0.1:${port}/v1/chat/completions" "$@")
  if [[ "$got" == "$expect" ]]; then
    printf 'PASS  %-3s (want %s)  %s\n' "$got" "$expect" "$name"
    ((pass++))
  else
    printf 'FAIL  %-3s (want %s)  %s\n' "$got" "$expect" "$name"
    ((fail++))
  fi
}

# Every access-log row Envoy has written so far, one JSON object per line.
rows() { docker logs "$CONTAINER" 2>/dev/null | grep '^{' }

# The row for one request id; polls briefly because the logger is asynchronous.
row() {
  local i line
  for i in {1..40}; do
    line=$(rows | grep -F "\"x-request-id\":\"$1\"")
    if [[ -n "$line" ]]; then print -r -- "$line"; return 0; fi
    sleep 0.1
  done
  return 1
}

# Assert one field of the LAST request's access-log row. `$2` is a JSON literal (`"allow"`,
# `20790000`, `true`, `null`) compared after parsing, so types are checked, not just text.
field() {
  local key="$1" want="$2" line got
  line=$(row "$LAST_RID")
  if [[ -z "$line" ]]; then
    printf 'FAIL  no access-log row for %s  %s\n' "$LAST_RID" "$LAST_NAME"; ((fail++)); return
  fi
  if printf '%s' "$line" | python3 -c '
import json, sys
d = json.load(sys.stdin)
sys.exit(0 if d.get(sys.argv[1]) == json.loads(sys.argv[2]) else 1)' "$key" "$want"; then
    printf 'PASS  row %-24s = %-14s %s\n' "$key" "$want" "$LAST_NAME"; ((pass++))
  else
    got=$(printf '%s' "$line" | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin).get(sys.argv[1])))' "$key")
    printf 'FAIL  row %-24s = %s (want %s)  %s\n' "$key" "$got" "$want" "$LAST_NAME"; ((fail++))
  fi
}

# Assert the LAST request produced NO row at all (the format's `matches` predicate dropped it).
no_row() {
  sleep 0.3
  if rows | grep -qF "\"x-request-id\":\"$LAST_RID\""; then
    printf 'FAIL  a row was logged for %s  %s\n' "$LAST_RID" "$LAST_NAME"; ((fail++))
  else
    printf 'PASS  no row logged           %s\n' "$LAST_NAME"; ((pass++))
  fi
}

echo "── enforce mode: the balance decides ─────────────────────────────────────────"
check 'remaining > 0 -> allowed'                             200 10100 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=20790000,account_id=acct_1' \
  -H 'x-ai-eg-model: gemma-4'
check 'remaining == 0 -> 402 budget_exhausted'               402 10100 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=0,account_id=acct_1' \
  -H 'x-ai-eg-model: gemma-4'
check 'remaining < 0 (overspent) -> 402'                     402 10100 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=-1000000,account_id=acct_1' \
  -H 'x-ai-eg-model: gemma-4'
check 'remaining of exactly 1 micro-USD -> allowed'          200 10100 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=1,account_id=acct_1' \
  -H 'x-ai-eg-model: gemma-4'

echo
echo "── unknown is NEVER zero ─────────────────────────────────────────────────────"
check 'known=false -> 503, NOT 402'                          503 10100 \
  -H 'x-test-budget: enforced=true,known=false,account_id=acct_1' \
  -H 'x-ai-eg-model: gemma-4'
check 'metadata absent + model present -> 503'               503 10100 \
  -H 'x-ai-eg-model: gemma-4'
check 'known=true but no number -> 503 (the two sides drifted)' 503 10100 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=nonsense,account_id=acct_1' \
  -H 'x-ai-eg-model: gemma-4'

echo
echo "── requests this filter must not touch ───────────────────────────────────────"
check 'metadata absent + no model -> allowed (non-AI route)' 200 10100
check 'enforced=false (internal plane) -> allowed'           200 10100 \
  -H 'x-test-budget: enforced=false,known=false' -H 'x-ai-eg-model: gemma-4'
check 'enforced absent -> treated as not-enforced, allowed'  200 10100 \
  -H 'x-test-budget: known=true,remaining_micros=0' -H 'x-ai-eg-model: gemma-4'

echo
echo "── shadow mode refuses NOTHING ───────────────────────────────────────────────"
check 'shadow + exhausted -> still allowed'                  200 10101 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=0,account_id=acct_1' \
  -H 'x-ai-eg-model: gemma-4'
check 'shadow + unknown -> still allowed'                    200 10101 \
  -H 'x-test-budget: enforced=true,known=false' -H 'x-ai-eg-model: gemma-4'
check 'shadow + metadata absent + model -> still allowed'    200 10101 \
  -H 'x-ai-eg-model: gemma-4'

echo
echo "── the safe default is shadow, not enforcement ───────────────────────────────"
check 'NO config table + exhausted -> allowed (defaults to shadow)' 200 10102 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=0,account_id=acct_1' \
  -H 'x-ai-eg-model: gemma-4'

echo
echo "── the script cannot crash the enforcement open ──────────────────────────────"
check 'script raises, pcall guard present -> 503'            503 10103 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=99,account_id=acct_1' \
  -H 'x-ai-eg-model: gemma-4'
check 'script raises, guard REMOVED -> reaches upstream (guard is load-bearing)' 200 10104 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=99,account_id=acct_1' \
  -H 'x-ai-eg-model: gemma-4'

echo
echo "── the 402 body is well-formed JSON, even for a hostile account id ───────────"
body=$(curl -s "http://127.0.0.1:10100/v1/chat/completions" \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=0,account_id=evil","injected":"yes,next_reset_at=2026-10-01T00:00:00Z' \
  -H 'x-ai-eg-model: gemma-4')
echo "$body"
if printf '%s' "$body" | python3 -c '
import json,sys
d = json.load(sys.stdin)
assert "injected" not in d, d
assert d["error"] == "budget_exhausted", d
assert d["remaining_micros"] == 0, d
assert d["refill_url"] == "https://example.test/budget", d
assert d["next_reset_at"] == "2026-10-01T00:00:00Z", d
assert d["message"], d
print("PASS  402 body parses as JSON, carries the contract, and no injected key")
' 2>/dev/null; then
  ((pass++))
else
  echo "FAIL  the 402 body was not safe, well-formed, contract-shaped JSON"; ((fail++))
fi

echo
echo "── the 503 body is distinguishable from the 402 body ─────────────────────────"
body=$(curl -s "http://127.0.0.1:10100/v1/chat/completions" \
  -H 'x-test-budget: enforced=true,known=false' -H 'x-ai-eg-model: gemma-4')
echo "$body"
if printf '%s' "$body" | python3 -c '
import json,sys
d = json.load(sys.stdin)
assert d["error"] == "budget_unavailable", d
assert "remaining_micros" not in d, d
print("PASS  503 body says budget_unavailable and carries no balance")
' 2>/dev/null; then
  ((pass++))
else
  echo "FAIL  the 503 body was not the documented budget_unavailable shape"; ((fail++))
fi

echo
echo "── (a) the chart's access-log row: what shadow mode measures (ai-helm#1097) ──"
# Rows are the ONLY observable shadow mode has: the allow path logs nothing, and decisions live in
# the `lightbridge.budget_limiter` metadata namespace the four `budget.*` fields read. In this
# harness the sink is a typed-JSON file, so an absent field is `null`; prod's OTel attribute sink
# stringifies the same absence to `-`.
check 'allowed -> row: allow / within_budget / remaining / shadow=false / via_upstream' 200 10100 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=20790000,account_id=acct_1' \
  -H 'x-ai-eg-model: gemma-4'
field budget.decision '"allow"'
field budget.reason '"within_budget"'
field budget.remaining_micros 20790000
field budget.shadow false
field response_code_details '"via_upstream"'

check 'refused 402 -> row: deny / budget_exhausted, and it is lua_response' 402 10100 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=0,account_id=acct_1' \
  -H 'x-ai-eg-model: gemma-4'
field budget.decision '"deny"'
field budget.reason '"budget_exhausted"'
field budget.remaining_micros 0
field response_code_details '"lua_response"'

check 'shadow would-refuse -> 200, row still says deny, shadow=true' 200 10101 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=0,account_id=acct_1' \
  -H 'x-ai-eg-model: gemma-4'
field budget.decision '"deny"'
field budget.reason '"budget_exhausted"'
field budget.shadow true
field response_code_details '"via_upstream"'

check 'refused 503 (unknown) -> row: deny / budget_unknown, no remaining' 503 10100 \
  -H 'x-test-budget: enforced=true,known=false,account_id=acct_1' -H 'x-ai-eg-model: gemma-4'
field budget.reason '"budget_unknown"'
field budget.remaining_micros null
field response_code_details '"lua_response"'

# The one row shape that shares `budget.decision: -` with the incident: the script raised. It is
# still lua_response, and still a 503 -- never a 500, never direct_response.
check 'script raised inside pcall -> 503, budget.* all absent, lua_response' 503 10103 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=99,account_id=acct_1' \
  -H 'x-ai-eg-model: gemma-4'
field budget.decision null
field budget.reason null
field response_code_details '"lua_response"'

# The `matches` predicate: a request with no x-ai-eg-model is not a model request and is NOT
# logged. This is also why non-model traffic is invisible in Loki (see the values-repo runbook).
check 'no model header -> not a model request, and no row is written' 200 10100 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=20790000,account_id=acct_1'
no_row

echo
echo "── (b) the metadata shapes prod's two AuthConfigs actually publish ───────────"
# Lifted from ai-helm-values environments/prod/values/security-policies.yaml,
# `response.success.dynamicMetadata.budget` on each AuthConfig, and the Stage 1 probe in its
# docs/runbooks/budget-limiter-rollout.md. Empty `k=` is the empty string, as CEL `""` publishes.

# INTERNAL plane: five constants. Every failing 2026-09-03 request carried exactly this.
INTERNAL='enforced=false,known=false,remaining_micros=0,next_reset_at=,account_id='
check 'internal plane shape, enforcing -> allowed'                200 10100 \
  -H "x-test-budget: $INTERNAL" -H 'x-ai-eg-model: deepseek-v4-flash-0731'
field budget.decision '"allow"'
field budget.reason '"not_enforced_on_this_plane"'
field budget.remaining_micros null
field response_code_details '"via_upstream"'
check 'internal plane shape, shadow -> allowed'                   200 10101 \
  -H "x-test-budget: $INTERNAL" -H 'x-ai-eg-model: deepseek-v4-flash-0731'
field budget.reason '"not_enforced_on_this_plane"'
field budget.shadow true
check 'internal plane shape, NO config table -> allowed'          200 10102 \
  -H "x-test-budget: $INTERNAL" -H 'x-ai-eg-model: deepseek-v4-flash-0731'
field budget.reason '"not_enforced_on_this_plane"'

# MAIN plane, the read succeeded: the numbers are the Stage 1 probe's, verbatim.
check 'main plane, read succeeded -> allowed, remaining recorded'  200 10100 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=7997430,next_reset_at=2026-09-07T00:00:00Z,account_id=49534505-4c60-4550-83dd-7af22152cec6' \
  -H 'x-ai-eg-model: gemma-4'
field budget.reason '"within_budget"'
field budget.remaining_micros 7997430

# MAIN plane, the read FAILED: the AuthConfig's CEL publishes `known: false` AND
# `remaining_micros: 0`. The zero must never be read as "exhausted".
check 'main plane, read failed publishes remaining=0 -> 503, NOT 402' 503 10100 \
  -H 'x-test-budget: enforced=true,known=false,remaining_micros=0,next_reset_at=,account_id=49534505-4c60-4550-83dd-7af22152cec6' \
  -H 'x-ai-eg-model: gemma-4'
field budget.reason '"budget_unknown"'

# MAIN plane, no resolvable account id: the `when` gate skips the fetch, so the same
# known=false/0 shape arrives with an empty account_id. Fails closed under enforcement -- by
# design (an unmetered model request is the thing this filter exists to refuse), and worth
# knowing before Stage 3.
check 'main plane, account id unresolvable -> 503 budget_unknown'   503 10100 \
  -H 'x-test-budget: enforced=true,known=false,remaining_micros=0,next_reset_at=,account_id=' \
  -H 'x-ai-eg-model: gemma-4'
field budget.reason '"budget_unknown"'
check 'main plane, account id unresolvable, shadow -> allowed'      200 10101 \
  -H 'x-test-budget: enforced=true,known=false,remaining_micros=0,next_reset_at=,account_id=' \
  -H 'x-ai-eg-model: gemma-4'
field budget.decision '"deny"'
field budget.reason '"budget_unknown"'

# MAIN plane, genuinely exhausted, with the period boundary the ledger reports.
check 'main plane, exhausted -> 402 with the ledger next_reset_at'  402 10100 \
  -H 'x-test-budget: enforced=true,known=true,remaining_micros=0,next_reset_at=2026-10-01T00:00:00Z,account_id=49534505-4c60-4550-83dd-7af22152cec6' \
  -H 'x-ai-eg-model: gemma-4'
field budget.reason '"budget_exhausted"'

echo
echo "── the incident's signature cannot come from inside this filter ──────────────"
# Over EVERY row this run logged -- allow, 402, 503, shadow would-deny, a raise inside the guard,
# a raise with the guard removed -- none is `response_code_details: direct_response` and none is a
# 500. That pair is Envoy Gateway's router answering for a policy its controller refused
# (ai-helm-values#367, fixed in ai-helm#1098), and it is decided before any Envoy exists.
if rows | python3 -c '
import json, sys
rows = [json.loads(l) for l in sys.stdin if l.strip()]
assert rows, "no access-log rows at all"
details = sorted({r["response_code_details"] for r in rows})
codes = sorted({r["response_code"] for r in rows})
assert "direct_response" not in details, details
assert 500 not in codes, codes
print(f"PASS  {len(rows)} rows; response_code_details in {details}; response codes {codes}")
'; then
  ((pass++))
else
  echo "FAIL  a row carried the incident signature (direct_response and/or 500)"; ((fail++))
fi

echo
echo "═════════════════════════════════════════════════════════════════════════════"
echo "passed: $pass   failed: $fail"
[[ $fail -eq 0 ]]
