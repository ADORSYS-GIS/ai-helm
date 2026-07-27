# GPU fleet — open follow-ups (as of 2026-07-27)

Punch-list left after bringing the two Hetzner GPU nodes into service: the
generic model-serving charts (ADR-0094/0095), OpenMythos-27B and Qwen3-8B-AWQ,
engine hardening (ADR-0097), the Deployment switch (ADR-0098), GPU telemetry,
dashboards, alerting, and Grafana branding (ADR-0099).

Everything below is **known and deliberate** — nothing here is a surprise waiting
to be discovered. Ordered by what blocks whom.

---

## 1. Needs a human — nobody else can do these

### 1.1 Discord webhooks ⚠️ blocks the channel switchover

**Updated 2026-07-27:** the plan changed. The channel originally added for GPU
alerts is now the **default receiver for everything**, and the project lead's
personal webhook moves aside under its own name:

| Contact point | Destination | State |
|---|---|---|
| `discord` | the **team** channel — default receiver, catch-all | enabled; still delivering to the lead's webhook until the property value is updated |
| `discord-stephane` | the project lead's webhook | **disabled** until its property exists |

Two actions in `ssegning-aws`, key `ai/camer/digital/prod/env`:

1. **UPDATE** `grafana_discord_webhook_url` → the **team** webhook URL.
   (The property is deliberately reused so the default receiver is never pointed
   at something that does not exist. Nothing breaks in the meantime — alerts
   simply keep arriving where they do today.)
2. **CREATE** `grafana_discord_webhook_url_stephane` → the lead's existing
   webhook URL. Then set `discord-stephane` to `enabled: true` in
   `charts/observability-dashboards/values.yaml`.

⚠️ **Order matters, and this is not theoretical.** Enabling a contact point whose
secret is missing makes Grafana reject the **entire notification policy tree**,
which stopped *all* alert delivery on 2026-07-27 — the default route included.
The chart now skips disabled contact points and any route referencing them, so
the failure is contained, but the rule stands: **secret first, then flip the
flag.**

There is no route to `discord-stephane` today; the team channel being the
default means everything already lands there. The nine model/GPU rules keep their
`team: model-serving` label for silences and filters, and re-adding a route is a
three-line change documented in the values file.

### 1.2 `z-image-turbo-local` returns HTTP 500 ⚠️ user-visible

Verified against its correct endpoint (`/v1/images/generations`, not chat
completions — it is an image model). Its server is `enabled: true` and runs on
the **`admin@homeos`** cluster, for which there is no kubeconfig here, so it
could not be diagnosed.

Deliberately left advertised rather than silently disabled — hiding it would hide
the bug. Either fix it on that cluster or set `enabled: false` in
`charts/ai-models/values.yaml` as a conscious call.

### 1.3 Confirm the €184/month figure

ADR-0096's pricing derives from Hetzner's **published list price** for GEX44, not
a confirmed invoice. Setup fees, IPv4 charges or a negotiated rate would shift
every per-token number proportionally. Check billing, then re-tune.

### 1.4 Colleagues seeing `glm-5p1` in Kilo Code

That model was retired in ADR-0075 and exists in neither the catalog nor as a
route. Almost certainly a client-side cached model list — ask them to clear it
before treating it as a platform bug.

### 1.5 Grafana Enterprise — a budget decision, not an engineering one

ADR-0099: the Grafana logo, login page, favicon and browser title remain
Grafana's, because white-labeling is Enterprise-only. If that matters, it is a
licence purchase. Decide it on the whole feature set and price, not on branding
alone.

---

## 2. Measurement gaps — the numbers we are currently guessing

### 2.1 No concurrency benchmarks

Every measurement so far is **single-stream**. Both benchmark reports say so
explicitly. Consequences:

- vLLM's continuous batching — the main reason to run that engine — is entirely
  unexercised.
- The saturation alert thresholds (llama.cpp deferring, vLLM waiting) are
  *reasoned*, not calibrated against a load test.

`inference-ops` already names the tools of record: GuideLLM, NVIDIA aiperf,
inference-perf. A concurrency sweep on both tiers would turn several assumptions
into facts.

### 2.2 LMCache is enabled but unproven — and may be costing performance

`qwen3-8b-fast` runs with LMCache on. The connector initialises, but:

- a single-stream smoke test with no shared prefixes exercises none of its value;
- there are **no LMCache metrics**, so Grafana cannot tell you whether it helps;
- vLLM warns at start-up that `--kv-transfer-config` **disables the hybrid KV
  cache manager**, and that models with sliding-window attention "run with
  reduced performance" — Qwen3 uses sliding-window attention in some configs.

So it is plausibly a net negative right now. Needs an A/B with a shared-prefix
workload before it is assumed to be a win.

### 2.3 The 3.45× duty-cycle uplift is inherited, not measured

ADR-0096 reuses the utilisation assumption implied by the old A2000 entry
(~29% duty cycle). Nothing on this fleet has been measured. If real usage is much
busier we over-recover; much quieter and we under-recover. Re-tune once there is
real utilisation data.

### 2.4 `inputPer1M` is conservative-high fleet-wide

The catalog uses a `1 : 0.15 : 0.03` out/in/cached ratio. Measured prefill is
625 tok/s against 15 tok/s decode — **41× faster** — so physics would justify
input nearer `0.024`. Kept at 0.15 for consistency with existing entries; worth a
fleet-wide decision rather than a per-model exception.

---

## 3. Known platform limitations

### 3.1 `/v1/models` still lists internal-only models

`/v1/models` is generated by Envoy AI Gateway from the AIGatewayRoutes and cannot
be filtered from our charts. Six `disableExternal: true` models therefore still
appear to external clients, which get a correct-but-confusing
`404 No matching route found` if they pick one.

Mitigated, not fixed: those models now report `owned_by: "GIS AI Models (internal
only)"`, the only field the OpenAI model schema offers (there is no display-name
field). `/v1/models/info` — which we do control — filters them out entirely.

A genuine fix needs AIEG to make `/v1/models` listener-aware. Worth an upstream
issue.

### 3.2 Any `grafana.ini` change wipes all dashboards

Grafana is stateless (ADR-0023), so changing `grafana.ini` rolls the pod and
destroys its emptyDir — taking every operator-provisioned **folder** and
dashboard with it. The operator's cached "synchronized" status means it does not
recreate the folders, so every `folderRef` dashboard then fails with
`[400] "folder not found"`. `resyncPeriod` alone does **not** recover this.

Remedy, verified 2026-07-27 (28/28 dashboards back within 15s):

```bash
kubectl rollout restart -n observability deploy/grafana-operator
```

Worth automating — or revisiting ADR-0023 and giving Grafana a small PVC.

### 3.3 No token-rate regression alert

Nothing fires if a model falls below its benchmarked decode rate — arguably the
most useful alert we could have. `llamacpp:predicted_tokens_seconds` is a
last-value gauge that persists while idle, so a single slow generation would
latch an alert on indefinitely. Needs a sustained measure neither engine
currently exports; a recording rule over a time window is the likely shape.

### 3.4 No GPU-to-cost attribution

DCGM tells us which pod is on which card; the gateway tells us what each request
cost. Nothing joins them, so "what did this model actually cost to run this
month" still needs manual arithmetic.

---

## 4. Hygiene / deferred

| Item | Note |
|---|---|
| Engine containers run as **root** with all caps dropped | Tightening to non-root is a per-engine follow-up gated on a real GPU rollout; a previous attempt to pin `runAsUser: 1000` was written but never verified (ADR-0094) |
| Eight legacy `charts/model-serving-*` charts | Retained because `zimage-turbo` is live on `admin@homeos`; retire with that cluster. **Do not copy their shape** |
| `homeCluster: true` | Now legacy-only (ADR-0095); should retire with the above |
| `inference-ops` tutorial not yet run by a non-author | That repo's own rule requires it before merge; the page carries a validation-status note |
| Two ADRs numbered `0077` | Pre-existing (`my-usage-dashboard`, `phoenix-style-chat-dashboards`). Cosmetic, needs a renumber |
| `dcgm-exporter` label transition | Flipping `honorLabels` left the old `exported_*` series in the TSDB; they age out with retention. Cosmetic only |

---

## Related

- ADRs: [0094](../adr/0094-generic-model-serving-orchestrator.md) ·
  [0095](../adr/0095-cluster-local-model-federation.md) ·
  [0096](../adr/0096-gex44-fleet-cost-recovery-pricing.md) ·
  [0097](../adr/0097-engine-agnostic-serving-hardening.md) ·
  [0098](../adr/0098-deployment-recreate-instead-of-statefulset.md) ·
  [0099](../adr/0099-grafana-branding-within-oss-limits.md)
- Pattern: [`../patterns/self-hosted-model-serving.md`](../patterns/self-hosted-model-serving.md)
- Inference knowledge, runbooks and benchmark reports: the **`inference-ops`** repo
