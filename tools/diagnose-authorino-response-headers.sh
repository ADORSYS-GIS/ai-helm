#!/usr/bin/env bash
# diagnose-authorino-response-headers.sh
#
# PURPOSE — Finding 2 confirmation (intermittent x-oidc-* / identity header loss).
#
# In the per-user dashboard, Authorino-injected access-log fields (user_id,
# oidc_email, oidc_name, oidc_iss, …) intermittently render as "-" per request,
# for an IDENTICAL token, while native Envoy fields (x-request-id, method,
# duration) are always present. There is no time/config/resource correlation
# (verified) and NO documented bug in Authorino or Envoy that matches.
#
# A "-" in the OTLP/Loki access log cannot, by itself, distinguish:
#   (A) header truly ABSENT from the request   → Authorino auth path  → SEVERE
#       (rate-limiting keyed on x-account-id would be intermittently bypassed)
#   (B) header present, Envoy %REQ() formatter dropped it → OTel access-log bug
#   (C) header present+rendered, OTLP→Alloy serialization dropped the attribute
#       (B)/(C) are OBSERVABILITY-ONLY — auth + rate-limiting are fine.
#
# This script runs the DECISIVE primary test: capture what Authorino ACTUALLY
# EMITS (logLevel=debug) for the same requests, then correlate by x-request-id
# against the Loki line.
#   - Authorino debug shows all configured response headers  → (A) is FALSE,
#     the auth path is innocent and it's an Envoy/OTLP observability bug (B/C).
#   - Authorino debug shows a SUBSET                          → (A), it's Authorino.
#
# ⚠️ This PATCHES a live, critical auth component (Authorino logLevel) and
# reverts it. It is a DIAGNOSTIC, not infra — run it deliberately, capture
# quickly, let it revert. Debug logging is verbose; keep the window short.
# (If the Authorino CR is GitOps-managed, ArgoCD self-heal may also revert the
# logLevel shortly after — that's fine; capture within the window.)
#
# Prereqs: kubectl ctx with access to the workload cluster; the operator
# applies logLevel changes by rolling the Authorino deployment.
set -euo pipefail

CTX="${CTX:-hetzner-prod}"
NS="${NS:-converse-gateway}"
AUTHORINO="${AUTHORINO:-kuadrant-policies-main}"     # the Authorino CR / deploy
LOKI_NS="${LOKI_NS:-observability}"
CAPTURE_DIR="${CAPTURE_DIR:-/tmp/authorino-finding2-$(date +%Y%m%d-%H%M%S)}"
K="kubectl --context $CTX -n $NS"

confirm() { read -r -p "$1 [y/N] " a; [[ "$a" == y || "$a" == Y ]]; }

# ── correlate mode: given an x-request-id, show Authorino's emitted headers vs Loki
if [[ "${1:-}" == "correlate" ]]; then
  RID="${2:?usage: $0 correlate <x-request-id> [authorino-debug.log]}"
  LOG="${3:-$(ls -t /tmp/authorino-finding2-*/authorino-debug.log 2>/dev/null | head -1)}"
  echo "▶ Authorino debug lines mentioning $RID (what Authorino emitted):"
  grep -i "$RID" "$LOG" 2>/dev/null || echo "  (none — debug may not stamp the request id; grep by user/time instead)"
  echo ""
  echo "▶ Loki access-log line for $RID (what got logged):"
  kubectl --context "$CTX" -n "$LOKI_NS" port-forward svc/loki-gateway 3100:80 >/dev/null 2>&1 &
  PF=$!; sleep 5
  curl -s -G 'http://localhost:3100/loki/api/v1/query_range' \
    --data-urlencode "query={service_name=\"envoy-ai-gateway\"} | json | x_request_id=\"$RID\"" \
    --data-urlencode "start=$(date -d '30 min ago' +%s)000000000" \
    --data-urlencode "end=$(date +%s)000000000" --data-urlencode 'limit=1' \
    -H 'X-Scope-OrgID: anonymous' \
   | python3 -c "import sys,json;d=json.load(sys.stdin);r=d['data']['result'];print(json.dumps(json.loads(r[0]['values'][0][1]),indent=1)) if r else print('  (no Loki line)')" 2>&1
  kill $PF 2>/dev/null || true
  exit 0
fi

# ── capture mode (default)
mkdir -p "$CAPTURE_DIR"
echo "▶ Finding-2 capture → $CAPTURE_DIR"
echo "  context=$CTX ns=$NS authorino=$AUTHORINO"
ORIG=$($K get authorino "$AUTHORINO" -o jsonpath='{.spec.logLevel}' 2>/dev/null || echo "")
echo "  current logLevel: '${ORIG:-<unset>}'"
confirm "Patch Authorino logLevel=debug on the LIVE cluster (will roll the deployment)?" || { echo "aborted."; exit 1; }

revert() {
  echo "▶ reverting logLevel to '${ORIG:-<unset>}'…"
  if [[ -n "$ORIG" ]]; then
    $K patch authorino "$AUTHORINO" --type merge -p "{\"spec\":{\"logLevel\":\"$ORIG\"}}" >/dev/null
  else
    $K patch authorino "$AUTHORINO" --type json -p '[{"op":"remove","path":"/spec/logLevel"}]' >/dev/null 2>&1 || true
  fi
  echo "  done (ArgoCD self-heal will also re-assert the GitOps value if managed)."
}
trap revert EXIT

$K patch authorino "$AUTHORINO" --type merge -p '{"spec":{"logLevel":"debug"}}' >/dev/null
echo "▶ waiting for Authorino to roll with debug logging…"
$K rollout status deploy/"$AUTHORINO" --timeout=120s 2>/dev/null || sleep 20

# Authorino pods are labeled `authorino-resource=<name>` (set by the operator),
# NOT `app=<name>`. Verify the selector matches BEFORE tailing so we never
# silently capture an empty log again.
SEL="authorino-resource=$AUTHORINO"
NPODS=$($K get pods -l "$SEL" --no-headers 2>/dev/null | grep -c Running || true)
if [[ "${NPODS:-0}" -lt 1 ]]; then
  echo "✖ no Running pods match -l $SEL — check the label with:"
  echo "    $K get pods --show-labels | grep $AUTHORINO"
  exit 1
fi
echo "▶ tailing $NPODS Authorino pod(s) [$SEL] → $CAPTURE_DIR/authorino-debug.log"
$K logs -l "$SEL" --all-containers --prefix -f --since=10s \
  > "$CAPTURE_DIR/authorino-debug.log" 2>&1 &
TAIL=$!
sleep 3
if [[ ! -s "$CAPTURE_DIR/authorino-debug.log" ]]; then
  echo "  (no log output yet — that's fine; Authorino logs on request. Send traffic now.)"
fi

cat <<EOF

  ┌─ NOW: send 8–10 test prompts through the gateway ────────────────────────┐
  │  • LibreChat (internal plane)  AND  opencode (external plane), same user. │
  │  • Note a couple of x-request-ids if you can, or just generate volume.    │
  │  • The goal: capture requests that the dashboard later shows with "-".    │
  └───────────────────────────────────────────────────────────────────────────┘

EOF
read -r -p "Press Enter when you've sent the test traffic to stop the capture… " _
kill $TAIL 2>/dev/null || true

echo ""
LINES=$(wc -l < "$CAPTURE_DIR/authorino-debug.log")
echo "▶ captured $LINES log lines."
if [[ "$LINES" -lt 5 ]]; then
  echo "  ⚠️ that's suspiciously few — debug may not have been active or no traffic"
  echo "     hit these pods. Re-run and ensure traffic flows DURING the capture."
fi
echo "▶ preview — lines that look response/identity-related (does debug expose headers?):"
grep -iE "response|header|x-oidc|account-id|billing|authpipeline|cel" \
  "$CAPTURE_DIR/authorino-debug.log" 2>/dev/null | head -5 || true
echo "  …(if NONE of the above show the emitted headers, Authorino debug doesn't"
echo "     surface them — fall back to a 2nd text access-log sink + an Envoy tap)."
echo "▶ NEXT — decide A vs B/C:"
echo "   1. In Grafana/Loki, find a recent request from your test user whose"
echo "      identity fields show '-'. Copy its x-request-id."
echo "   2. Run:  $0 correlate <x-request-id> $CAPTURE_DIR/authorino-debug.log"
echo "   3. Read the Authorino debug lines for that request:"
echo "        • emitted ALL response headers  → auth path INNOCENT; it's the"
echo "          Envoy OTel access-log / OTLP path (observability-only). Then the"
echo "          follow-up is a 2nd text access-log sink to split formatter vs OTLP."
echo "        • emitted a SUBSET              → Authorino is dropping them; file"
echo "          an upstream Kuadrant issue with this capture + test the v0.26.1 bump."
echo ""
echo "  (logLevel reverts automatically on exit.)"
