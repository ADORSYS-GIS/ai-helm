# gateway-usage-backfill (one-off)

Backfills **historical** AI-Gateway usage metrics into Mimir so the cost
dashboards' 30-day view is populated retroactively — not just forward from when
[ADR-0058](../../docs/adr/0058-precompute-gateway-usage-metrics-to-mimir.md) part
A (Alloy `stage.metrics`) deployed.

**This is plain manifests, NOT a chart / ArgoCD app.** It lives in `hack/` so
ArgoCD (which only watches `charts/apps`) ignores it. Run it by hand.

## What it does

A `Job` in the `observability` namespace, three stages over a shared `emptyDir`:

1. **extract** (`python:3.12-slim`) — queries Loki per day (last 30) for
   `sum by (model,azp,display_name,billing_plan)` of cost / tokens / requests,
   and writes **cumulative** OpenMetrics samples to `/work/usage.om`. This is the
   slow step (reads old chunks from the rate-limited object store; per-day
   chunking + retries keep it under `SlowDown`).
2. **build-blocks** (`prom/prometheus` → `promtool tsdb create-blocks-from
   openmetrics`) — turns that into Prometheus TSDB blocks in `/work/blocks`.
3. **upload** (`grafana/mimirtool backfill`) — uploads the blocks to Mimir via
   the compactor's block-upload API (tenant `anonymous`).

The series carry the exact live metric names (`loki_process_custom_gen_ai_*`) +
`source="backfill"`, so the dashboards' `increase(...[1d])` spans history
(backfill) and recent (live) seamlessly via `sum by (...)`.

## Prerequisites

- Mimir `limits.compactor_block_upload_enabled: true` — enabled in
  `ai-helm-values` `environments/prod/values/mimir.yaml` (deploys via ArgoCD).
  Confirm the compactor has restarted with it before running.

## Run

```bash
KCTX="--context admin@homeos"   # ArgoCD cluster? NO — workloads are on Hetzner:
export KUBECONFIG=/Users/selast/dev/personal/hetzner-k8s/kubeconfig

kubectl apply -f hack/gateway-usage-backfill/        # configmap + job
kubectl -n observability logs -f job/gateway-usage-backfill -c extract
kubectl -n observability logs -f job/gateway-usage-backfill -c upload   # after init done
```

Re-run (idempotent — mimirtool skips already-uploaded blocks):

```bash
kubectl -n observability delete job gateway-usage-backfill
kubectl apply -f hack/gateway-usage-backfill/job.yaml
```

## After upload: making the blocks queryable (IMPORTANT)

`mimirtool backfill` finishing ("succeeded=N") only puts the blocks in object
storage. They do NOT become queryable until Mimir propagates them — which
happens on component intervals (~15–30 min total) OR you nudge it:

1. **Compactor** blocks-cleaner folds the new blocks into `bucket-index.json.gz`
   (runs on `compactor.cleanup-interval`). Force: `kubectl -n observability
   rollout restart statefulset/mimir-compactor` (cleaner runs on startup, after
   the ring stabilises ~1–5 min).
2. **Store-gateway** loads blocks listed in the bucket-index (on its sync
   interval). Force: `rollout restart statefulset/mimir-store-gateway` — confirm
   with `kubectl logs ... | grep -c 01KW0` (your new block ULIDs).
3. **Querier** discovers the store-gateway's blocks. If queries still return
   nothing after 1+2, `rollout restart deployment/mimir-querier`.

Order matters: compactor → store-gateway → querier. (Cost a half-hour of
"why is it empty" the first time.)

> ⚠️ The backfill series are **gauge-typed** (cumulative), so PromQL emits a
> harmless info: *"metric might not be a counter, name does not end in _total"*.
> `increase()` computes correctly regardless. First cold `increase[30d]` over all
> series is slow (~60s — reads the 1ms-wide blocks); the Mimir results/chunks
> caches make repeats fast.

## Verify

Query Mimir for backfilled series, then check a dashboard 30d view fills in.
Use `-H 'Cache-Control: no-store'` to bypass the results-cache while checking:

```bash
kubectl -n observability port-forward svc/mimir-nginx 18090:80 &
curl -s -H 'X-Scope-OrgID: anonymous' \
  'http://localhost:18090/prometheus/api/v1/query?query=count(loki_process_custom_gen_ai_requests{source="backfill"})'
```

## Undo

Backfilled samples are tagged `source="backfill"`. To remove them, delete the
uploaded blocks (they're tagged in their `meta.json`), or use Mimir's delete-series
API for `{source="backfill"}` over the backfilled range. The live forward metrics
are untouched.

## Tuning

- `DAYS` env on the `extract` container (default 30; Loki retention is 90).
- If `extract` times out on `SlowDown`, lower concurrency is already 1/day with
  retries; just re-run — it resumes (mimirtool skips done blocks; extract restarts
  the day loop but is cheap to redo).
