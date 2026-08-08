# Patterns

Reusable patterns, concept explainers, and reference/research write-ups — the
"how we think about X" docs. See the [docs index](../README.md) for the other
categories.

| File | What it covers |
|---|---|
| [coder-declarative-templates.md](coder-declarative-templates.md) | Declarative Coder template management via the `coder/coderd` Terraform provider (GitOps, retire `coder templates push`) — decision + implementation pattern (ADR-0123) |
| [self-hosted-model-serving.md](self-hosted-model-serving.md) | **The model-agnostic serving pattern** on the home GPU (VRAM budgeting, engine choice, "deploy the next model" checklist) |
| [self-hosted-code-interpreter.md](self-hosted-code-interpreter.md) | Self-hosted LibreChat Code Interpreter (ADR-0122): secret generation checklist, install verification, known limitations |
| [per-user-observability.md](per-user-observability.md) | Per-user attribution: JWT → Authorino headers → Envoy access log → Loki labels |
| [cost-observability.md](cost-observability.md) | AI-gateway cost observability (ADR-0058/0059/0060): Mimir metrics, cost dashboards + scoreboard, Discord alerting |
| [ratelimit-quota-observability.md](ratelimit-quota-observability.md) | Rate-limit quota from the limiter's LIVE Redis counters (ADR-0070) |
| [jwt-token-observability.md](jwt-token-observability.md) | Per-JWT (`oidc_jti`) consumption + last usages (ADR-0067) |
| [chat-observability.md](chat-observability.md) | Phoenix-style chat content from the gateway's OpenInference traces (ADR-0077/0079) |
| [observability-gaps.md](observability-gaps.md) | Service-by-service observability inventory + P0/P1/P2 ranking (#354/#341) |
| [observability-dashboard-research.md](observability-dashboard-research.md) | Dashboard gap inventory + OSS dashboard evaluation (ADR-0045/0046) |
| [shared-cross-model-budget.md](shared-cross-model-budget.md) | Shared cross-model monthly budget design (#532) |
| [redirect-308-explained.md](redirect-308-explained.md) | Why 308 (vs 301/302/307) matters for APIs |
| [bifrost-comprehensive-report.md](bifrost-comprehensive-report.md) | Bifrost vs Envoy AI Gateway — technical comparison |
| [2026-06-08-gpu-platform-procurement-comparison.md](2026-06-08-gpu-platform-procurement-comparison.md) | 🔬 GPU make-vs-buy research: A2000 vs 5×V100 vs Hetzner; TCO + ADR-0028 pricing |
| [authorino-service-account-bypass.md](authorino-service-account-bypass.md) | **Historical** (OPA removed, ADR-0021): how SA tokens used to skip OPA in Authorino |
| [mlops-access-model.md](mlops-access-model.md) | **Who can reach LakeFS / Argo Workflows / MLflow, and as what** — humans vs workloads vs external scripts, credential inventory, the end-to-end training-job path |
