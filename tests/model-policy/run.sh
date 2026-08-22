#!/usr/bin/env zsh
# Behaviour tests for the per-project model-allowlist filter (ADR-0133, ai-helm-values#292).
#
# Drives charts/core-gateway/files/model-policy.lua -- byte-for-byte the script the
# EnvoyExtensionPolicy embeds -- through a real Envoy, on the exact image the prod gateway
# data plane runs. 200 means the request reached the upstream; 403 means the filter refused.
#
#   ./tests/model-policy/run.sh          (needs docker, curl, python3)
#
# Ports 10000-10002 must be free. The container is removed on exit.
set -u

HERE="${0:a:h}"
IMAGE="envoyproxy/envoy:distroless-v1.38.3"
CONTAINER="model-policy-envoy-test"

cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true }
trap cleanup EXIT

python3 "$HERE/render-envoy-config.py" || exit 1
cleanup
docker run -d --name "$CONTAINER" \
  -p 10000:10000 -p 10001:10001 -p 10002:10002 \
  -v "$HERE/envoy.yaml:/etc/envoy/envoy.yaml:ro" \
  "$IMAGE" -c /etc/envoy/envoy.yaml --log-level warn >/dev/null || exit 1

for _ in {1..30}; do
  curl -s -o /dev/null "http://127.0.0.1:10000/" && break
  sleep 1
done

pass=0
fail=0

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

echo "── contract: x-model-policy drives the decision ──────────────────────────────"
check 'allow_all + any model -> allowed'                    200 10000 \
  -H 'x-model-policy: allow_all' -H 'x-allowed-models: gemma-4' -H 'x-ai-eg-model: anything-at-all'
check 'allow_all + empty list + any model -> allowed'       200 10000 \
  -H 'x-model-policy: allow_all' -H 'x-allowed-models;' -H 'x-ai-eg-model: gpt-5'
check 'allowlist + model IN list -> allowed'                200 10000 \
  -H 'x-model-policy: allowlist' -H 'x-allowed-models: gemma-4,minimax-m3' -H 'x-ai-eg-model: minimax-m3'
check 'allowlist + model NOT in list -> REFUSED'            403 10000 \
  -H 'x-model-policy: allowlist' -H 'x-allowed-models: gemma-4' -H 'x-ai-eg-model: minimax-m3'
check 'allowlist + EMPTY list -> REFUSED (ADR-0018)'        403 10000 \
  -H 'x-model-policy: allowlist' -H 'x-allowed-models;' -H 'x-ai-eg-model: gemma-4'
check 'allowlist + list header absent -> REFUSED'           403 10000 \
  -H 'x-model-policy: allowlist' -H 'x-ai-eg-model: gemma-4'
check 'allowlist + whitespace-only list -> REFUSED'         403 10000 \
  -H 'x-model-policy: allowlist' -H 'x-allowed-models:    ' -H 'x-ai-eg-model: gemma-4'
check 'policy "" (internal plane) -> no restriction'        200 10000 \
  -H 'x-model-policy;' -H 'x-allowed-models;' -H 'x-ai-eg-model: gemma-4'

echo
echo "── fail-closed ───────────────────────────────────────────────────────────────"
check 'allowlist + model undeterminable -> REFUSED'         403 10000 \
  -H 'x-model-policy: allowlist' -H 'x-allowed-models: gemma-4'
check 'allowlist + empty model header -> REFUSED'           403 10000 \
  -H 'x-model-policy: allowlist' -H 'x-allowed-models: gemma-4' -H 'x-ai-eg-model;'
check 'policy absent + model PRESENT -> REFUSED'            403 10000 \
  -H 'x-ai-eg-model: gemma-4'
check 'policy absent + model absent -> allowed (non-AI route)' 200 10000
check 'unrecognised policy deny_all -> REFUSED'             403 10000 \
  -H 'x-model-policy: deny_all' -H 'x-ai-eg-model: gemma-4'
check 'unrecognised policy garbage -> REFUSED'              403 10000 \
  -H 'x-model-policy: allowlistx' -H 'x-allowed-models: gemma-4' -H 'x-ai-eg-model: gemma-4'

echo
echo "── membership is exact, not fuzzy ────────────────────────────────────────────"
check 'list "a, b , c" tolerates spaces -> allowed'         200 10000 \
  -H 'x-model-policy: allowlist' -H 'x-allowed-models: gemma-4, minimax-m3 , gpt-5' -H 'x-ai-eg-model: minimax-m3'
check 'case differs -> REFUSED'                             403 10000 \
  -H 'x-model-policy: allowlist' -H 'x-allowed-models: Gemma-4' -H 'x-ai-eg-model: gemma-4'
check 'prefix of a listed id -> REFUSED'                    403 10000 \
  -H 'x-model-policy: allowlist' -H 'x-allowed-models: gpt-5-mini' -H 'x-ai-eg-model: gpt-5'
check 'listed id is a prefix of request -> REFUSED'         403 10000 \
  -H 'x-model-policy: allowlist' -H 'x-allowed-models: gpt-5' -H 'x-ai-eg-model: gpt-5-mini'

echo
echo "── header spoofing ───────────────────────────────────────────────────────────"
check 'duplicate policy header (allowlist + spoofed allow_all) -> REFUSED' 403 10000 \
  -H 'x-model-policy: allowlist' -H 'x-model-policy: allow_all' \
  -H 'x-allowed-models: gemma-4' -H 'x-ai-eg-model: minimax-m3'
check 'duplicate allowed-models header (real + spoofed widens list) -> REFUSED' 403 10000 \
  -H 'x-model-policy: allowlist' -H 'x-allowed-models: gemma-4' -H 'x-allowed-models: minimax-m3' \
  -H 'x-ai-eg-model: minimax-m3'
check 'duplicate model header -> REFUSED'                   403 10000 \
  -H 'x-model-policy: allowlist' -H 'x-allowed-models: gemma-4' \
  -H 'x-ai-eg-model: gemma-4' -H 'x-ai-eg-model: gemma-4'

echo
echo "── the script cannot crash the enforcement open ──────────────────────────────"
check 'script raises, pcall guard present -> REFUSED'       403 10001 \
  -H 'x-model-policy: allow_all' -H 'x-ai-eg-model: gemma-4'
check 'script raises, guard REMOVED -> reaches upstream (guard is load-bearing)' 200 10002 \
  -H 'x-model-policy: allow_all' -H 'x-ai-eg-model: gemma-4'

echo
echo "── the refusal body is well-formed JSON even for a hostile model id ──────────"
body=$(curl -s "http://127.0.0.1:10000/v1/chat/completions" \
  -H 'x-model-policy: allowlist' -H 'x-allowed-models: gemma-4' \
  -H 'x-ai-eg-model: evil","injected":"yes')
echo "$body"
if printf '%s' "$body" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert "injected" not in d, d; print("PASS  body parses as JSON and carries no injected key")' 2>/dev/null; then
  ((pass++))
else
  echo "FAIL  refusal body was not safe JSON"; ((fail++))
fi

echo
echo "═════════════════════════════════════════════════════════════════════════════"
echo "passed: $pass   failed: $fail"
[[ $fail -eq 0 ]]
