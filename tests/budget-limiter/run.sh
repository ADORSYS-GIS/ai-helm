#!/usr/bin/env zsh
# Behaviour tests for the Dynamic Budget Limiter's enforcement filter
# (lightbridge-authz ADR-0034, lightbridge-authz#658).
#
# Drives charts/core-gateway/files/budget-limiter.lua -- byte-for-byte the script the
# EnvoyExtensionPolicy embeds -- through a real Envoy, on the exact image the prod gateway data
# plane runs. 200 means the request reached the upstream; 402 means the account is out of budget;
# 503 means the balance could not be determined, which is emphatically NOT the same answer.
#
#   ./tests/budget-limiter/run.sh          (needs docker, curl, python3)
#
# Ports 10100-10104 must be free. The container is removed on exit.
set -u

HERE="${0:a:h}"
IMAGE="envoyproxy/envoy:distroless-v1.38.3"
CONTAINER="budget-limiter-envoy-test"

cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true }
trap cleanup EXIT

python3 "$HERE/render-envoy-config.py" || exit 1
cleanup
docker run -d --name "$CONTAINER" \
  -p 10100:10100 -p 10101:10101 -p 10102:10102 -p 10103:10103 -p 10104:10104 \
  -v "$HERE/envoy.yaml:/etc/envoy/envoy.yaml:ro" \
  "$IMAGE" -c /etc/envoy/envoy.yaml --log-level warn >/dev/null || exit 1

for _ in {1..30}; do
  curl -s -o /dev/null "http://127.0.0.1:10100/" && break
  sleep 1
done

pass=0
fail=0

# `x-test-budget` is consumed by the harness's fake-Authorino filter (see
# render-envoy-config.py) and turned into the ext_authz dynamic metadata the real filter reads.
# Omitting it means "the AuthConfig published nothing at all".
check() {
  local name="$1" expect="$2" port="$3"; shift 3
  local got
  got=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}/v1/chat/completions" "$@")
  if [[ "$got" == "$expect" ]]; then
    printf 'PASS  %-3s (want %s)  %s\n' "$got" "$expect" "$name"
    ((pass++))
  else
    printf 'FAIL  %-3s (want %s)  %s\n' "$got" "$expect" "$name"
    ((fail++))
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
echo "═════════════════════════════════════════════════════════════════════════════"
echo "passed: $pass   failed: $fail"
[[ $fail -eq 0 ]]
