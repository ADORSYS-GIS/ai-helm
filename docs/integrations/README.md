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
| [librechat-headers-tracing.md](librechat-headers-tracing.md) | How LibreChat templated headers flow into downstream MCP/Converse calls |
| [opencode-well-known.md](opencode-well-known.md) | opencode `.well-known/opencode` flow at `ai.camer.digital` |
| [opencode-plugins-research.md](opencode-plugins-research.md) | OpenCode plugins/extensions research (toolbelt, skills, MCP surfaces) |
| [coder-platform-integration.md](coder-platform-integration.md) | Coder re-integration evaluation (ADR-0027 removal + re-intro reqs; issue #651) |
| [keycloak-identity-datasource.md](keycloak-identity-datasource.md) | Resolving `user_id` → person, sessions & grants (ADR-0063/0064) |
