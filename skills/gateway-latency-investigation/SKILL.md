---
name: gateway-latency-investigation
description: Investigate "the gateway/API is slow" reports in a Kubernetes + Envoy/Loki stack by separating network/routing/auth overhead from backend/upstream generation time, then localizing the outlier by dimension (model, route, user) and checking for config drift between git and the live cluster. Use when asked to find the cause of excessive latency, timeouts, or slowness in an Envoy Gateway / AI Gateway / service-mesh style deployment with Loki-queryable access logs.
---

# Gateway Latency Investigation

A repeatable method for turning a vague "the gateway is slow" complaint into a
proven, quantified root cause — without guessing and without trusting stale
docs. Built from a real investigation of an AI gateway (Envoy Gateway +
Envoy AI Gateway + Authorino + Kuadrant + LLM backends) where the actual cause
turned out to be uncapped LLM reasoning-effort tokens on one model family, not
the gateway/network stack at all.

The core insight: **always split total observed duration into "time to
reach/return from upstream" vs "everything else"** before hypothesizing about
infra causes. Most "gateway is slow" reports are actually "the backend is slow
to generate/stream," and no amount of Envoy/Authorino/network tuning will fix
that.

## When to use this

- Users/monitoring report slow requests, timeouts, or "the gateway got slow"
  on a Kubernetes ingress/gateway stack (Envoy Gateway, Envoy AI Gateway,
  Istio, generic reverse proxies) with structured access logs shipped to
  Loki/Elasticsearch/CloudWatch.
- Especially relevant for **LLM/AI gateways** where "slow" often means "long
  time-to-last-byte on a streamed response" rather than a networking problem.
- Do NOT use this for a single anecdotal report with no log access — first
  confirm you can query the access-log store described in Step 2.

## Step 0 — Don't trust stale investigation docs or your own assumptions

Before touching logs, grep the repo for prior investigation plans/ADRs/issues
about performance (e.g. `plans/`, `docs/adr/`, `docs/migrations/`). Treat them
as **hypotheses to verify, not conclusions** — architectures drift, and a
6-month-old plan built around a component that has since been removed
(a proxy hop, a Lua filter, a sidecar) will send you down a dead end. Confirm
every suspect component **currently exists** in the live cluster before
investigating it further (`kubectl get <kind> -A` for the specific CRD/
resource, not just "I recall it's there").

Also check: is there uncommitted/unpushed/undeployed work already sitting in
git that addresses part of the problem? (`git log origin/main..HEAD`,
`git status`.) If so, note it as a candidate fix but still prove causation
with data before recommending deploy-and-hope.

## Step 1 — Rule out resource/capacity starvation first (cheap, fast)

These are quick to check and eliminate whole categories of hypotheses:

```bash
# Pod-level CPU/mem vs requests/limits for every component in the request path
kubectl top pods -n <gateway-ns> -n <authz-ns> -n <control-plane-ns>

# HPA headroom — are we scaling, or pinned at min replicas with low utilization?
kubectl get hpa -A

# Node-level pressure
kubectl top nodes
```

If everything is well under its limits and HPAs aren't scaling under load,
capacity is not the cause — move on. Don't spend more time here.

## Step 2 — Find the access-log source and its useful fields

Identify the log-shipping path (Envoy access logs → OTLP/Fluentd/Alloy → Loki/
Elasticsearch is common). Port-forward to the query endpoint if needed:

```bash
kubectl port-forward -n <observability-ns> svc/loki-gateway 3100:80 &
```

Discover labels and pick the right stream:

```bash
curl -s "http://localhost:3100/loki/api/v1/labels" | jq
curl -s "http://localhost:3100/loki/api/v1/label/service_name/values" | jq
```

Pull a decent sample window (aim for hundreds-to-low-thousands of lines —
enough for percentile stats per dimension):

```bash
curl -s -G "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={service_name="<your-gateway-service>"} |= "duration"' \
  --data-urlencode 'start='$(date -d '2 hours ago' +%s)'000000000' \
  --data-urlencode 'end='$(date +%s)'000000000' \
  --data-urlencode 'limit=1000' \
  > /tmp/opencode/loki_result.json
```

Inspect a few raw log lines to learn the actual field names before writing
analysis code — access-log JSON schemas vary a lot between setups. Look
specifically for:
- A **total/client-observed duration** field (e.g. `duration`).
- An **upstream-only timing** field — this is the key one. Envoy exposes it
  as the `x-envoy-upstream-service-time` response header (time from request
  dispatch to receiving the response **headers** from upstream — i.e.
  time-to-first-byte, NOT full stream completion). Other proxies have
  equivalents (Istio: `X-Envoy-Upstream-Service-Time` too; nginx:
  `$upstream_response_time`; ALB: `target_processing_time`).
- A **response/completion classification** field (Envoy:
  `response_code_details` — values like `via_upstream`, `response_timeout`,
  `ext_authz_denied`, `downstream_remote_disconnect` tell you *where* a
  non-happy-path request failed without reading a single log line by hand).
- Whatever **dimension fields** exist to slice by later: route name, backend/
  model name, user/tenant id, token counts for LLM gateways
  (`gen_ai.usage.input_tokens` / `output_tokens`), protocol.

## Step 3 — The key technique: split "total duration" from "upstream time"

Compute percentiles (p50/p95/p99/max) for BOTH fields across your sample:

```python
import json, statistics

def to_f(v):
    try: return float(v)
    except Exception: return None

rows = []
with open('/tmp/opencode/loki_result.json') as f:
    data = json.load(f)
for stream in data['data']['result']:
    for ts, line in stream['values']:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        rows.append(obj)

def pctl(vals, p):
    vals = sorted(vals)
    return vals[int(len(vals) * p)] if vals else None

durations = [to_f(r.get('duration')) for r in rows if to_f(r.get('duration'))]
upstream  = [to_f(r.get('x-envoy-upstream-service-time')) for r in rows if to_f(r.get('x-envoy-upstream-service-time'))]

print("duration  p50/p95/p99/max:", pctl(durations,.5), pctl(durations,.95), pctl(durations,.99), max(durations))
print("upstream  p50/p95/p99/max:", pctl(upstream,.5),  pctl(upstream,.95),  pctl(upstream,.99),  max(upstream))
```

**Interpretation:**
- `duration` high AND `upstream_service_time` high, tracking together →
  the backend itself is slow to respond (or slow network path to it).
  Investigate the backend/provider.
- `duration` high, `upstream_service_time` low/flat → the extra time is
  spent AFTER headers are received — for streamed responses (SSE, chunked,
  LLM token streams) this almost always means **slow/long generation
  during the body stream**, not gateway overhead. For non-streamed APIs it
  can mean slow client consumption or a downstream buffering issue.
  Either way, Envoy/Authorino/auth/routing/tracing are NOT the cause — don't
  waste time tuning them further once this pattern is confirmed.
- Also tabulate `response_code_details` (or equivalent) counts. A cluster of
  `response_timeout` (or `504`) events tells you which requests hit a
  configured ceiling (check `BackendTrafficPolicy`/ingress annotation for the
  exact timeout value) — cross-reference which dimension (model/route/user)
  they belong to.

## Step 4 — Localize the outlier by slicing on dimensions

Group the same percentile stats by whatever dimension fields you found in
Step 2 (model, route, backend, tenant) — the goal is to find that latency is
NOT uniform, but concentrated in one slice:

```python
from collections import defaultdict
by_model = defaultdict(list)
for r in rows:
    if r.get('response_code_details') == 'via_upstream':  # happy path only
        d = to_f(r.get('duration'))
        if d: by_model[r.get('model') or r.get('gen_ai.request.model')].append(d)

for model, vals in sorted(by_model.items()):
    vals.sort()
    n = len(vals)
    print(model, 'n=', n, 'p50=', vals[n//2], 'p95=', vals[int(n*.95)], 'max=', vals[-1])
```

For LLM gateways specifically, also compute **effective throughput** —
visible-output-tokens per second of wall-clock duration:

```python
tps = []
for r in rows:
    if r.get('response_code_details') != 'via_upstream': continue
    d = to_f(r.get('duration'))
    o = to_f(r.get('gen_ai.usage.output_tokens'))
    if d and o and o > 0:
        tps.append(o * 1000.0 / d)  # tokens/sec, if duration is ms
```

A model/route whose visible tok/s is an order of magnitude below its peers,
while its upstream-service-time (TTFB) stays normal, is a strong signal of
**invisible reasoning/thinking tokens being generated but not counted** in
the output-token metric — i.e. the model is "thinking" for most of the
request's wall-clock time off the visible-token books. Cross-check this
against the backend's configured reasoning-effort/thinking settings.

## Step 5 — Check for live config drift (git vs cluster)

A fix can be written and committed but never actually deployed. Don't assume
git HEAD reflects the live cluster — verify directly:

```bash
# Compare git-desired value...
grep -n "samplingRate\|reasoningEffort\|<your-suspect-setting>" charts/**/values.yaml

# ...against what's actually applied
kubectl get <CRD-kind> -n <ns> -o yaml | grep -A2 "<your-suspect-setting>"
kubectl get cm -n <ns> -l app.kubernetes.io/name=<app> -o yaml | grep -c "<expected-new-key>"
```

If the grep count is 0 / the live value doesn't match git, you've found
undeployed drift — this is often the actual, simplest fix (sync/deploy),
not a new code change.

## Step 6 — Rule-out checklist before concluding

Before finalizing a root cause, make sure you've explicitly checked and
dismissed (with data, not assumption):
- [ ] Auth/identity provider latency (test the JWKS/token endpoint directly
      with a throwaway pod `curl`, don't just eyeball a warning log)
- [ ] Authz sidecar/service latency (ext_authz-style denial/allow timings)
- [ ] Resource starvation (Step 1)
- [ ] Retry/circuit-breaker policy amplifying load (check `numRetries`,
      `perRetry.timeout`, `maxParallelRequests` on any traffic policy CRs)
- [ ] Recurring warning-log noise that correlates with **nothing** in the
      duration data (e.g. benign control-plane reconnect messages) — don't
      let scary-looking logs distract from what the numbers show
- [ ] The actual configured request/stream timeout ceiling, so you know
      whether `response_timeout`-style events are "hit an artificial wall"
      vs "genuinely still working when killed"

## Step 7 — Report format

State the finding as: **(a)** the quantified split (duration vs upstream
time, with percentiles), **(b)** the specific dimension where it concentrates
(model/route/user) with numbers, **(c)** the mechanism (why that dimension is
slow — e.g. uncapped reasoning effort, oversized payloads, a specific
provider), **(d)** ruled-out causes with one-line evidence each so the reader
doesn't re-litigate them, **(e)** concrete next action (deploy pending fix /
open ticket with provider / config change), not just "investigate further."

## Reusable artifacts

See `references/loki_percentile_analysis.py` for a parameterized version of
the Step 3/4 analysis script — adjust the field names at the top for your
schema and point it at your saved Loki JSON response.
