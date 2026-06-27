# ai-helm documentation

Index of everything under `docs/`. Files are grouped by intent; if you don't
know where a topic lives, grep — file names are stable and descriptive.

> **Convention:** new docs go under one of the sections below. Long-form
> migration write-ups live in `docs/migrations/`. Operational subsystems with
> several files (backups, secrets, model gateway) get their own subdirectory
> with a local `README.md` that indexes the contents.

**Start here:** [`architecture.md`](./architecture.md) for the single-page system
map, the **[architecture suite](./architecture/README.md)** for the layered
deep-dive (C4 + per-subsystem, all mermaid), [`arc42.md`](./arc42.md) for the
formal description, [`adr/README.md`](./adr/README.md) for every architectural
decision, [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for how to ship a change.

---

## Architecture suite (layered, mermaid)

The primary architecture reference: a navigable set following the **C4 model**
(context → container → component) plus one page per cross-cutting subsystem.
Every diagram is mermaid; start at the hub and zoom in.

| File | Layer | Covers |
|---|---|---|
| [`architecture/README.md`](./architecture/README.md) | hub | How the layers relate; C4 ↔ arc42 map; diagram conventions |
| [`architecture/01-context.md`](./architecture/01-context.md) | C4 L1 | Actors + external systems (the one-box view) |
| [`architecture/02-containers.md`](./architecture/02-containers.md) | C4 L2 | Deployable units by namespace; render patterns |
| [`architecture/03-gateway-components.md`](./architecture/03-gateway-components.md) | C4 L3 | The gateway request path + 4 runtime sequences |
| [`architecture/04-gitops-deployment.md`](./architecture/04-gitops-deployment.md) | infra | Two-cluster GitOps, destinations, sync waves, release flow |
| [`architecture/05-auth-identity.md`](./architecture/05-auth-identity.md) | security | Dual-plane auth, identity surfaces, `x-oidc-*`, GitHub-OIDC binding |
| [`architecture/06-networking-tls.md`](./architecture/06-networking-tls.md) | infra | Ingress, Hetzner LB, Cilium deny-egress, TLS issuance |
| [`architecture/07-data-secrets.md`](./architecture/07-data-secrets.md) | infra | Mongo/CNPG/Redis/S3, the ESO secret flow, ownership split |
| [`architecture/08-observability.md`](./architecture/08-observability.md) | platform | LGTM pipeline, per-user attribution, dashboards-as-code |
| [`architecture/09-model-serving.md`](./architecture/09-model-serving.md) | platform | Provider fan-out + the self-hosted GPU model; budget tiers |
| [`architecture/10-mcp.md`](./architecture/10-mcp.md) | platform | MCP routing, the OAuth carve-out, external-proxy modes |

---

## Architecture & integration

How the system is wired and how to integrate against it.

| File | What it covers |
|---|---|
| [`observability-stack.md`](./observability-stack.md) | Mimir / Loki / Tempo / Alloy / Grafana topology, sync-wave ordering, data flow |
| [`observability-dashboards.md`](./observability-dashboards.md) | Per-subsystem dashboard inventory and instrumentation plan |
| [`observability-storage-retention.md`](./observability-storage-retention.md) | Retention windows, S3 bucket layout, cost trade-offs |
| [`cost-observability.md`](./cost-observability.md) | **AI-gateway cost observability** (ADR-0058/0059/0060): the Mimir metrics backbone (Alloy `stage.metrics`, why not the Loki ruler), the cost dashboards + gamified scoreboard (`$budget` gauge, deferred candlestick/flamegraph), Discord alerting, the one-off backfill, and the operator runbook. The "how it works + how to run it" for `retained ≠ queryable` on a rate-limited object store. |
| [`alloy-servicemonitor-guide.md`](./alloy-servicemonitor-guide.md) | How Alloy discovers ServiceMonitors and PodMonitors; clustering gotchas |
| [`grafana-operator-and-dashboards.md`](./grafana-operator-and-dashboards.md) | Grafana Operator install, dashboards-as-code, where dashboard JSON lives |
| [`keycloak-audience-operations.md`](./keycloak-audience-operations.md) | OIDC audience claim management; full-scope-allowed implications |
| [`librechat-oidc-integration.md`](./librechat-oidc-integration.md) | LibreChat ↔ Keycloak OIDC wiring, claim mapping, role propagation |
| [`librechat-oidc-experiments.md`](./librechat-oidc-experiments.md) | Notes from earlier OIDC iterations — kept as historical record |
| [`librechat_headers_tracing_doc.md`](./librechat_headers_tracing_doc.md) | How LibreChat templated headers flow into downstream MCP/Converse calls |
| [`authorino-service-account-bypass.md`](./authorino-service-account-bypass.md) | **Historical** (OPA removed 2026-06-04, ADR-0021): how service-account tokens used to skip OPA / external metadata in Authorino |
| [`per-user-observability.md`](./per-user-observability.md) | Per-user attribution: JWT → Authorino headers → Envoy access log → Loki `user_id`/`azp` labels |
| [`keycloak-identity-datasource.md`](./keycloak-identity-datasource.md) | **Resolving `user_id` → person, sessions & grants** (ADR-0063/0064): the read-only Keycloak Postgres `GrafanaDatasource` (`-ro` replica, least-privilege role), the user-directory + sessions-grants dashboards, the KC 26 persistent-sessions `offline_flag` trap, what's answerable vs not (no per-token budget), cross-repo layout + verify/rollback runbook |
| [`jwt-token-observability.md`](./jwt-token-observability.md) | **Per-JWT (`oidc_jti`) consumption + last usages** (ADR-0067): the `jwt-tokens` dashboard, email-from-JWT-claim-only (Loki `email` label, not the Keycloak DB), why it's Loki-backed (jti is body-only, never a Mimir label), the `oidc_jti`-same-`\| json`-extraction LogQL trap, cardinality, verify runbook |
| [`opencode-well-known.md`](./opencode-well-known.md) | opencode `.well-known/opencode` flow at `ai.camer.digital`; prerequisites, plugin install, troubleshooting |
| [`opencode-sandboxing.md`](./opencode-sandboxing.md) | Why the opencode permission config is **not** a sandbox (string-matched bash rules over code-execution tools), opencode's lack of a native OS sandbox (worktree = recovery only), the containment options (worktree / OS wrapper / devcontainer / hosted in-cluster), and the recommendation (devcontainer for local; hosted = future ADR reversing ADR-0027) |
| [`coder-analysis.md`](./coder-analysis.md) | Comprehensive Coder capability and architecture analysis: VS Code Remote, OpenCode integration, authentication flows, persistence strategies, security, cost analysis; investigation for potential Coder deployment (ADR-0027 evaluation context) |
| [`coder-platform-integration.md`](./coder-platform-integration.md) | Evaluation document for potential Coder re-integration: architecture, Keycloak OIDC, Grafana observability, LibreChat MCP integration, OpenCode auth flow; references ADR-0027 removal and re-introduction requirements |
| [`architecture.md`](./architecture.md) | System-level map: ArgoCD topology, sync waves, auth flow, observability pipeline, glossary |
| [`arc42.md`](./arc42.md) | Formal arc42 architecture description (12 sections): goals, constraints, context, building blocks, runtime/deployment views, crosscutting concepts, risks, glossary |
| [`architectural-shift-main-to-magical-bohr.md`](./architectural-shift-main-to-magical-bohr.md) | The full `main → claude/magical-bohr-390242` shift: 8 shifts (two-cluster Hetzner topology, LiteLLM removal, JWT authz, LGTM observability, GitOps structure, secrets, scale, dual-plane gateway) |
| [`2026-currency-audit.md`](./2026-currency-audit.md) | Helm chart + Kubernetes API + tooling currency audit, mid-2026 |
| [`2026-hetzner-cutover.md`](./2026-hetzner-cutover.md) | Hetzner cutover change-log (ADR-0018/19/20, domain switch, per-cluster knobs) + live fix-verification status + open items |
| [`observability-gaps.md`](./observability-gaps.md) | Service-by-service observability inventory (ticket #354, epic #341): every workload we run (+ externally-owned), its metrics/dashboard coverage, criticality, P0/P1/P2 ranking; findings (Keycloak traces dropped at a `debug` exporter; vestigial knative-serving); user/usage dashboard state. Companion: the dashboard-research doc below |
| [`observability-dashboard-research.md`](./observability-dashboard-research.md) | Dashboard gap inventory + open-source dashboard evaluation (tickets #354/#355, epic #341): live scrape/dashboard audit (6 of 13 imported boards dead from missing scrapes; per-user board root cause), per-service adopt/modify/custom recommendations with API-verified gnetIds, sequencing. Decisions: ADR-0045 (sourcing policy) + ADR-0046 (per-user attribution repair) |
| [`2026-06-07-observability-datasource-audit.md`](./2026-06-07-observability-datasource-audit.md) | Live diagnosis + fixes for the Grafana datasource breakages: Tempo `:3100`→`:3200`, Loki label mislabeling (line-regex → K8s service discovery), Mimir empty (wedged memberlist ring) + LGTM topology rationale ("why N pods?", "why no Prometheus?") |
| [`2026-06-10-mcp-external-server-proxy-debug.md`](./2026-06-10-mcp-external-server-proxy-debug.md) | Why external hosted MCPs (context7/firecrawl/refero) fail through the gateway while self-hosted (brave/terraform) work: NOT our config or ADR-0038 — an **AIEG v0.6.0 mcpproxy** bug (stateless-server 405-on-GET / SSE decode). Proof (upstreams return tools when hit directly from inside the cluster), the **AIEG v0.6.0→v0.7.0 upgrade** + compat audit, and the ⚠️ caveat that v0.7 may not fully fix it (file upstream if not) + reproduction recipe |
| [`2026-06-08-gpu-platform-procurement-comparison.md`](./2026-06-08-gpu-platform-procurement-comparison.md) | 🔬 **Research document** (advisory, not an ADR — see its §0 methodology/confidence) — **GPU make-vs-buy comparison**: local A2000 (DE) vs eBay 5×V100 + existing 2×4070 (both **Cameroon**) vs Hetzner GEX44/GEX131: hardware side-by-side, model-deployability + concurrency/users matrices (per backend: llama.cpp/vLLM/SGLang), **12/24/36-mo TCO** (V100 parametric over €2–4k + power sensitivity), **§6.3 Cameroon-electricity redo** (ENEO ~€0.16/kWh ≈ ½ German → V100 36-mo TCO drops below GEX44) + **§6.4 the already-owned 2×4070**, and **ADR-0028 cost-recovery pricing** applied to all. Comparisons are re-done against the **named June-2026 models** (Qwen3.5, Gemma 4, **GLM-4.7-Flash 30B-A3B**, 122B-A10B MoE) with **context windows** (§3.4) + **capabilities** (§3.3, multimodal/coding/reasoning) + **§6.5 maintenance/ops** (the ignored cost — it ~triples the owned V100's TCO and flips its RoI). **§9 RoI** for a 30–100 dev+marketing team vs budget SaaS: standout = the owned **2×4070 + GLM-4.7-Flash** (+$250/mo after maintenance); 70B is a conditional buy (V100 only if DIY-cheap ops; GEX131 at scale) |
| [`continuous-delivery.md`](./continuous-delivery.md) | **How deploys work (ADR-0055)** — continuous delivery: OCI-published charts floated on a semver range + argocd-image-updater write-back to the private `ai-helm-values` repo; the root tracks `main`. The model, the per-app onboarding recipe, rollback, gotchas. (Replaces the retired tag-based `releasing.md` + `tools/release.sh`.) |
| [`gateway-capacity.md`](./gateway-capacity.md) | Envoy AI Gateway readiness/capacity: config-ready-not-proven verdict, the 32-CPU cluster ceiling + HPA right-size `[3;20]→[3;5]`, the "average user that feels good" profile, what governs throughput (backends > cluster CPU > Envoy), next steps (artillery load test, add workers) |
| [`self-hosted-model-serving.md`](./self-hosted-model-serving.md) | **The model-agnostic pattern** for serving any self-hosted model/agent on the home GPU (bjw StatefulSet, pre-seeded RWX PVC, cluster-local + edge auth, gateway federation): VRAM budgeting, vLLM-vs-llama.cpp engine choice, cross-cutting gotchas, "deploy the next model" checklist + cost basis (ADR-0022/0028/0029/0030). Per-model specifics live in `docs/models/` ↓ |
| [`models/qwen3.5-4b-q4.md`](./models/qwen3.5-4b-q4.md) | **Qwen3.5-4B Q4 (llama.cpp)** paper (🟢 **LIVE**, ADR-0032) — the active self-hosted model: `charts/model-serving-qwen3-5`, `llama-server` + unsloth UD-Q4_K_XL GGUF, native `--api-key` (no Caddy), `/v1`. **§6 measured capacity/perf**: ~52 tok/s decode, ~1.3k prefill, 4 slots, 128k ctx (real 35k prompts) |
| [`models/qwen3-4b.md`](./models/qwen3-4b.md) | **Qwen3-4B** deployment paper (🟦 standby, disabled 2026-06-08 — rollback) — vLLM/huggingfaceserver + LMCache, BF16, 16k ctx; the reference build: as-built architecture, container args, gotchas, €/hour→per-token cost |
| [`models/qwen3.5-4b.md`](./models/qwen3.5-4b.md) | **Qwen3.5-4B (vLLM/BF16)** paper (📋 studied, not chosen) — the full-precision alternative + why vLLM's Qwen3.5 support is too turbulent to pick now |
| [`python-dashboard-generation.md`](./python-dashboard-generation.md) | How dashboards are generated from Python (grafana-foundation-sdk), the drift check, layouts |

## Architecture Decision Records

The **why** behind every meaningful architectural choice. See
[`docs/adr/README.md`](./adr/README.md) for the full index, status legend, and
how to add a new ADR.
| [`bifrost_comprehensive_report.md`](./bifrost_comprehensive_report.md) | Bifrost gateway evaluation report |
| [`service-endpoint-decommission.md`](./service-endpoint-decommission.md) | Decommission checklist for cluster-internal service endpoints |
| [`models-chart-docs/`](./models-chart-docs/) | `ai-models` chart deep-dive: cost tracking, rate-limit investigation, secret schema |

## Runbooks & operations

Step-by-step recipes for recurring or break-glass operations.

| File | When you'd open it |
|---|---|
| [`cnpg-native-backup/`](./cnpg-native-backup/) | CNPG `BarmanObjectStore` setup; `lightbridge-db` restore runbook + restore YAMLs |
| [`mongodb-restoration-guide.md`](./mongodb-restoration-guide.md) | Restore a MongoDB backup into the `librechat-db` StatefulSet |
| [`observability-fix-no-data-dashboards.md`](./observability-fix-no-data-dashboards.md) | Postmortem + fix for empty Grafana dashboards (Alloy clustering, OTLP fan-out) |
| [`secret-management/`](./secret-management/) | Bootstrap secret inventory, ExternalSecret reference patterns |

## Migrations

Permanent record of meaningful one-way changes (deletions, replatforms).

| File | What changed |
|---|---|
| [`migrations/phoenix-to-tempo.md`](./migrations/phoenix-to-tempo.md) | Arize Phoenix removed; LLM tracing now served by Grafana Tempo |
| [`2026-linode-to-hetzner-cutover.md`](./2026-linode-to-hetzner-cutover.md) | Linode→Hetzner production cutover + domain rename `ai-v2`→`ai` (ADR-0025): ordered DNS-gated sequence, the LibreChat Mongo migration script, rollback |

> When you make a one-way change (delete an app, swap a backing store, rename a
> public-facing host), add a file here. Future-you will not remember why.

## Repo-root patterns

Pattern docs that live at the repo root because they describe the repo itself,
not a subsystem. Linked here for discoverability.

- [`../SYNC_WAVE_PATTERN.md`](../SYNC_WAVE_PATTERN.md) — ArgoCD sync-wave ordering for the monitoring stack
- [`../MONITORING_FIX.md`](../MONITORING_FIX.md) — Postmortem for the `monitoring-quota` ownership race

> **Drift note:** the audit recommends moving both of these under `docs/`. They
> stay at root for now to preserve their git history; consider a future move
> with `git mv`.

## Stale / cleanup candidates

- `librechat-oidc-experiments.md` — exploratory; consider archiving under `docs/archive/` once the production OIDC setup is stable.
