# ai-helm documentation

Index of everything under `docs/`. Topical docs are grouped into four
directories by **intent**; cross-cutting subsystems keep their own subdirectory.

| Directory | Intent — open it when you want to… |
|---|---|
| [`playbooks/`](./playbooks/) | **do** something — a step-by-step runbook, setup, or how-to |
| [`integrations/`](./integrations/) | **integrate** a specific product/surface (LibreChat, opencode, Coder, Keycloak-as-IdP) |
| [`patterns/`](./patterns/) | understand a **reusable pattern**, concept, or reference/research write-up |
| [`migrations/`](./migrations/) | read the **permanent record** of a cutover, upgrade, or point-in-time audit |

> **Convention:** a new doc goes in one of the four dirs above (or an existing
> subsystem subdir). Front-matter docs (`architecture.md`, `arc42.md`,
> `continuous-delivery.md`, `commit-conventions.md`) stay at `docs/` root. Each
> topical dir carries a local `README.md` index.

**Start here:** [`architecture.md`](./architecture.md) for the single-page system
map · the **[architecture suite](./architecture/README.md)** for the layered
deep-dive (C4 + per-subsystem, all mermaid) · [`arc42.md`](./arc42.md) for the
formal description · [`adr/README.md`](./adr/README.md) for every architectural
decision · [`continuous-delivery.md`](./continuous-delivery.md) for how deploys
work · [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for how to ship a change.

---

## Architecture suite (layered, mermaid)

The primary architecture reference: a navigable set following the **C4 model**
(context → container → component) plus one page per cross-cutting subsystem.
Every diagram is mermaid (uncolored, client-rendered); start at the hub and zoom in.

| File | Layer | Covers |
|---|---|---|
| [`architecture/README.md`](./architecture/README.md) | hub | How the layers relate; C4 ↔ arc42 map; diagram conventions |
| [`architecture/01-context.md`](./architecture/01-context.md) | C4 L1 | Actors + external systems (the one-box view) |
| [`architecture/02-containers.md`](./architecture/02-containers.md) | C4 L2 | Deployable units by namespace; render patterns |
| [`architecture/03-gateway-components.md`](./architecture/03-gateway-components.md) | C4 L3 | The gateway request path + runtime sequences |
| [`architecture/04-gitops-deployment.md`](./architecture/04-gitops-deployment.md) | infra | Two-cluster GitOps, destinations, sync waves, delivery flow |
| [`architecture/05-auth-identity.md`](./architecture/05-auth-identity.md) | security | Dual-plane auth, identity surfaces, `x-oidc-*`, GitHub-OIDC binding |
| [`architecture/06-networking-tls.md`](./architecture/06-networking-tls.md) | infra | Ingress, Hetzner LB, Cilium deny-egress, TLS issuance |
| [`architecture/07-data-secrets.md`](./architecture/07-data-secrets.md) | infra | Mongo/CNPG/Redis/S3, the ESO secret flow, ownership split |
| [`architecture/08-observability.md`](./architecture/08-observability.md) | platform | LGTM pipeline, per-user attribution, dashboards-as-code |
| [`architecture/09-model-serving.md`](./architecture/09-model-serving.md) | platform | Provider fan-out + the self-hosted GPU model; budget tiers |
| [`architecture/10-mcp.md`](./architecture/10-mcp.md) | platform | MCP routing, the OAuth carve-out, external-proxy modes |

---

## Playbooks — [`playbooks/`](./playbooks/)

Step-by-step runbooks, setup guides, and break-glass recipes.

| File | When you'd open it |
|---|---|
| [`observability-stack.md`](playbooks/observability-stack.md) | Mimir / Loki / Tempo / Alloy / Grafana topology, sync-wave ordering, data flow |
| [`observability-dashboards.md`](playbooks/observability-dashboards.md) | Per-subsystem dashboard inventory and instrumentation plan |
| [`observability-storage-retention.md`](playbooks/observability-storage-retention.md) | Retention windows, S3 bucket layout, cost trade-offs |
| [`observability-fix-no-data-dashboards.md`](playbooks/observability-fix-no-data-dashboards.md) | Postmortem + fix for empty Grafana dashboards (Alloy clustering, OTLP fan-out) |
| [`alloy-servicemonitor-guide.md`](playbooks/alloy-servicemonitor-guide.md) | How Alloy discovers ServiceMonitors/PodMonitors; clustering gotchas |
| [`grafana-operator-and-dashboards.md`](playbooks/grafana-operator-and-dashboards.md) | Grafana Operator install, dashboards-as-code, where dashboard JSON lives |
| [`python-dashboard-generation.md`](playbooks/python-dashboard-generation.md) | How dashboards are generated from Python (grafana-foundation-sdk), the drift check, layouts |
| [`gateway-capacity.md`](playbooks/gateway-capacity.md) | Envoy AI Gateway readiness/capacity: the 32-CPU ceiling, HPA right-size, throughput governors, load-test next steps |
| [`keycloak-audience-operations.md`](playbooks/keycloak-audience-operations.md) | OIDC audience claim management; full-scope-allowed implications |
| [`keycloak-billing-provisioning-guide.md`](playbooks/keycloak-billing-provisioning-guide.md) | Exporting the billing-plan claim Keycloak → Envoy Gateway |
| [`mongodb-restoration-guide.md`](playbooks/mongodb-restoration-guide.md) | Restore a MongoDB backup into the `librechat-db` StatefulSet |
| [`service-endpoint-decommission.md`](playbooks/service-endpoint-decommission.md) | Decommission checklist for cluster-internal service endpoints |
| [`opencode-sandboxing.md`](playbooks/opencode-sandboxing.md) | Why the opencode permission config is **not** a sandbox; the containment options + recommendation |

---

## Integrations — [`integrations/`](./integrations/)

How to integrate against, or consume, a specific product or surface.

| File | What it covers |
|---|---|
| [`librechat-platform.md`](integrations/librechat-platform.md) | LibreChat platform component — the chat UI + its dependencies |
| [`librechat-oidc-integration.md`](integrations/librechat-oidc-integration.md) | LibreChat ↔ Keycloak OIDC wiring, claim mapping, role propagation |
| [`librechat-oidc-experiments.md`](integrations/librechat-oidc-experiments.md) | Notes from earlier OIDC iterations — kept as historical record |
| [`librechat-chain-of-agents.md`](integrations/librechat-chain-of-agents.md) | Chain-of-Agent use-case catalogue (#414/#409): five multi-agent patterns + cross-cutting findings + candidate ranking |
| [`librechat-headers-tracing.md`](integrations/librechat-headers-tracing.md) | How LibreChat templated headers flow into downstream MCP/Converse calls |
| [`opencode-well-known.md`](integrations/opencode-well-known.md) | opencode `.well-known/opencode` flow at `ai.camer.digital`; prerequisites, plugin install, troubleshooting |
| [`opencode-plugins-research.md`](integrations/opencode-plugins-research.md) | OpenCode plugins/extensions research (the vymalo toolbelt, skills, MCP surfaces) |
| [`coder-platform-integration.md`](integrations/coder-platform-integration.md) | Coder re-integration evaluation: Keycloak OIDC, Grafana, LibreChat MCP, OpenCode auth (ADR-0027 removal + re-intro reqs; issue #651) |
| [`keycloak-identity-datasource.md`](integrations/keycloak-identity-datasource.md) | Resolving `user_id` → person, sessions & grants (ADR-0063/0064): read-only Keycloak Postgres datasource, the dashboards, the KC 26 `offline_flag` trap, cross-repo layout + runbook |
| [`homepage.md`](integrations/homepage.md) | Homepage central hub — the `gethomepage.dev/*` discovery-annotation convention for adding new apps to the hub (ADR-0089) |

---

## Patterns — [`patterns/`](./patterns/)

Reusable patterns, concept explainers, and reference/research write-ups.

| File | What it covers |
|---|---|
| [`self-hosted-model-serving.md`](patterns/self-hosted-model-serving.md) | **The model-agnostic serving pattern** on the home GPU (bjw StatefulSet, RWX PVC, cluster-local + edge auth, gateway federation): VRAM budgeting, vLLM-vs-llama.cpp, gotchas, "deploy the next model" checklist + cost basis (ADR-0022/0028/0029/0030). Per-model specifics in [`models/`](./models/) |
| [`per-user-observability.md`](patterns/per-user-observability.md) | Per-user attribution: JWT → Authorino headers → Envoy access log → Loki `user_id`/`azp` labels |
| [`cost-observability.md`](patterns/cost-observability.md) | **AI-gateway cost observability** (ADR-0058/0059/0060): the Mimir metrics backbone (Alloy `stage.metrics`), the cost dashboards + gamified scoreboard, Discord alerting, the backfill, and the operator runbook |
| [`ratelimit-quota-observability.md`](patterns/ratelimit-quota-observability.md) | **Rate-limit quota from the limiter's LIVE Redis counters** (ADR-0070): the key shape (`rule-2`=free/`rule-7`=pro, `<window>`=bucket epoch), the exporter→Mimir leaderboard + the `redis-datasource` tmscan census (`tlsAuth:true` gotcha) |
| [`jwt-token-observability.md`](patterns/jwt-token-observability.md) | **Per-JWT (`oidc_jti`) consumption + last usages** (ADR-0067): the `jwt-tokens` dashboard, email-from-JWT-claim-only, why it's Loki-backed, the same-`\| json`-extraction LogQL trap |
| [`chat-observability.md`](patterns/chat-observability.md) | **Phoenix-style chat content from the gateway's OpenInference traces** (ADR-0077 + 0079): the `chat-overview` / `chats-by-user` dashboards; why per-user CONTENT is a confirmed structural dead-end (ext-proc precedes Authorino) |
| [`observability-gaps.md`](patterns/observability-gaps.md) | Service-by-service observability inventory (#354/#341): every workload, its coverage, criticality, P0/P1/P2 ranking; findings |
| [`observability-dashboard-research.md`](patterns/observability-dashboard-research.md) | Dashboard gap inventory + OSS dashboard evaluation (#354/#355): the live scrape/dashboard audit; adopt/modify/custom recommendations (ADR-0045/0046) |
| [`shared-cross-model-budget.md`](patterns/shared-cross-model-budget.md) | Shared cross-model monthly budget design (#532) |
| [`redirect-308-explained.md`](patterns/redirect-308-explained.md) | HTTP redirection: why 308 (vs 301/302/307) matters for APIs |
| [`bifrost-comprehensive-report.md`](patterns/bifrost-comprehensive-report.md) | Bifrost vs Envoy AI Gateway — technical comparison / evaluation report |
| [`2026-06-08-gpu-platform-procurement-comparison.md`](patterns/2026-06-08-gpu-platform-procurement-comparison.md) | 🔬 **Research** (advisory, not an ADR) — GPU make-vs-buy: A2000 vs 5×V100 vs Hetzner GEX44/GEX131; deployability + concurrency matrices, 12/24/36-mo TCO, Cameroon-electricity redo, ADR-0028 pricing applied |
| [`authorino-service-account-bypass.md`](patterns/authorino-service-account-bypass.md) | **Historical** (OPA removed 2026-06-04, ADR-0021): how SA tokens used to skip OPA / external metadata in Authorino |

---

## Migrations — [`migrations/`](./migrations/)

Permanent record of meaningful one-way changes — cutovers, replatforms, upgrades,
and point-in-time audits. When you make a one-way change, add a file here.

| File | What changed |
|---|---|
| [`phoenix-to-tempo.md`](migrations/phoenix-to-tempo.md) | Arize Phoenix removed; LLM tracing now served by Grafana Tempo (ADR-0002) |
| [`2026-linode-to-hetzner-cutover.md`](migrations/2026-linode-to-hetzner-cutover.md) | Linode→Hetzner production cutover + domain rename `ai-v2`→`ai` (ADR-0025): DNS-gated sequence, the Mongo migration script, rollback |
| [`2026-hetzner-cutover.md`](migrations/2026-hetzner-cutover.md) | Hetzner cutover change-log (ADR-0018/19/20, domain switch, per-cluster knobs) + live fix-verification status + open items |
| [`2026-currency-audit.md`](migrations/2026-currency-audit.md) | Helm chart + Kubernetes API + tooling currency audit, mid-2026 |
| [`2026-06-07-observability-datasource-audit.md`](migrations/2026-06-07-observability-datasource-audit.md) | Live diagnosis + fixes for Grafana datasource breakages: Tempo `:3100`→`:3200`, Loki mislabeling, wedged Mimir ring + LGTM topology rationale |
| [`2026-06-10-mcp-external-server-proxy-debug.md`](migrations/2026-06-10-mcp-external-server-proxy-debug.md) | Why external hosted MCPs fail through the gateway — an AIEG mcpproxy bug — + the v0.6.0→v0.7.0 upgrade + repro recipe |
| [`architectural-shift-main-to-magical-bohr.md`](migrations/architectural-shift-main-to-magical-bohr.md) | The full `main → claude/magical-bohr-390242` shift: 8 shifts (Hetzner topology, LiteLLM removal, JWT authz, LGTM, GitOps, secrets, scale, dual-plane gateway) |

---

## Subsystem subdirectories

Operational subsystems with several files keep their own directory + local index.

| Directory | Covers |
|---|---|
| [`adr/`](./adr/) | **Architecture Decision Records** — the *why* behind every meaningful choice; see [`adr/README.md`](./adr/README.md) for the index, status legend, and how to add one |
| [`models/`](./models/) | Per-model deployment papers (Qwen3.5-4B Q4 **LIVE**, Qwen3-4B standby, Qwen3.5-4B vLLM studied) |
| [`models-chart-docs/`](./models-chart-docs/) | `ai-models` chart deep-dive: cost tracking, rate-limit investigation, secret schema |
| [`cnpg-native-backup/`](./cnpg-native-backup/) | CNPG `BarmanObjectStore` setup; `lightbridge-db` restore runbook + restore YAMLs |
| [`secret-management/`](./secret-management/) | Bootstrap secret inventory, ExternalSecret reference patterns |
| [`opencode-integration/`](./opencode-integration/) | opencode client integration (VS Code, JetBrains, CLI, PR reviews, desktop) |
| [`github-actions/`](./github-actions/) | The GitHub Actions / CI integration surface |
| [`mcp/`](./mcp/) | Envoy MCP research + routing background |
| [`solutions-team/`](./solutions-team/) | Solutions-team runbooks (e.g. graphify setup) |

---

## Repo-root patterns

Pattern docs that live at the repo root because they describe the repo itself,
not a subsystem. Linked here for discoverability.

- [`../SYNC_WAVE_PATTERN.md`](../SYNC_WAVE_PATTERN.md) — ArgoCD sync-wave ordering for the monitoring stack
- [`../MONITORING_FIX.md`](../MONITORING_FIX.md) — Postmortem for the `monitoring-quota` ownership race
