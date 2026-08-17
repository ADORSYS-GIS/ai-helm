# Integrations

How to integrate against, or consume, a specific product or surface — LibreChat,
opencode, Coder, Keycloak-as-IdP. See the [docs index](../README.md) for the
other categories.

| File | What it covers |
|---|---|
| [librechat-platform.md](librechat-platform.md) | LibreChat platform component — the chat UI + its dependencies |
| [librechat-oidc-integration.md](librechat-oidc-integration.md) | LibreChat ↔ Keycloak OIDC wiring, claim mapping, role propagation |
| [librechat-oidc-experiments.md](librechat-oidc-experiments.md) | Notes from earlier OIDC iterations — historical record |
| [librechat-chain-of-agents.md](librechat-chain-of-agents.md) | Chain-of-Agent use-case catalogue (#414/#409) |
| [librechat-rag.md](librechat-rag.md) | Native RAG limits — file-size caps, file-type support, failure modes (#413/#409) |
| [librechat-headers-tracing.md](librechat-headers-tracing.md) | How LibreChat templated headers flow into downstream MCP/Converse calls |
| [opencode-well-known.md](opencode-well-known.md) | opencode `.well-known/opencode` flow at `ai.camer.digital` |
| [opencode-plugins-research.md](opencode-plugins-research.md) | OpenCode plugins/extensions research (toolbelt, skills, MCP surfaces) |
| [coder-platform-integration.md](coder-platform-integration.md) | Coder re-integration evaluation (ADR-0027 removal + re-intro reqs; issue #651) |
| [coder-workspace-urls.md](coder-workspace-urls.md) | Public workspace URLs via wildcard subdomains — and why the wildcard can't live under `ai.camer.digital` (Route53 delegation vs the Cloudflare DNS-01 solver) |
| [keycloak-identity-datasource.md](keycloak-identity-datasource.md) | Resolving `user_id` → person, sessions & grants (ADR-0063/0064) |
| [homepage.md](homepage.md) | Homepage central hub — the `gethomepage.dev/*` discovery-annotation convention for adding new apps (ADR-0089) |
| [mlops-platform-consumer-guide.md](mlops-platform-consumer-guide.md) | **Using the MLOps platform from another repo/team** — endpoints, how a script or training job authenticates to LakeFS/MLflow/Argo, and the end-to-end training recipe |
| [webank-training-deployment.md](webank-training-deployment.md) | **Webank governed dataset and training deployment** — the ten public Argo templates, GPU placement, LakeFS credential boundary, and model-specific contracts |
