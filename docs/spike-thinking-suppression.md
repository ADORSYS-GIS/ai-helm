# Research: Constraining Reasoning Model Thinking Output

**Date:** 2026-07-10
**Status:** Research complete — recommendations ready for team review
**Ticket:** AI Governance sprint — "annoying" reasoning output
**Scope:** Evaluate candidate levers to reduce/suppress thinking output from reasoning models

---

## Summary

Reasoning models (GLM-5.2, Kimi K2.5/K2.6, DeepSeek-V4, Qwen3, MiniMax M2.5) emit verbose thinking output by default. Users find it annoying; it costs output tokens. We investigated three candidate avenues to address this:

| Avenue | Scope | Effort | Recommendation |
|--------|-------|--------|----------------|
| **A: opencode `.well-known` config** | opencode users (org-wide) | Config-only (YAML) | **Primary** — ship first |
| **B: Kilo Code `kilo.jsonc` config** | Kilo users (per-user) | Config-only, but distributed | **Secondary** — document for users |
| **C: Gateway ExtProc patch** | All gateway traffic | Go code required | **Future** — if central enforcement needed |

All three avenues suppress the same underlying API parameter (`thinking`, `reasoning_effort`, or `enable_thinking`). The difference is *where* the parameter gets injected and *who controls* it.

---

## Background

### The Problem

Our model catalog (`charts/ai-models/values.yaml`) declares `reasoning` as a supported parameter for thinking-capable models. The `/v1/models/info` endpoint surfaces this to clients. But **nothing currently sets the parameter** — the catalog declares support without configuring behavior.

When thinking is enabled, reasoning models emit verbose `reasoning_content` alongside their actual answer. Both consume output tokens:

- **With thinking enabled:** 2,000–8,000 reasoning tokens + 500–2,000 answer tokens per request
- **With thinking disabled:** 0 reasoning tokens + 500–2,000 answer tokens per request

The thinking output is visible in the TUI (toggleable via `/thinking` — display only, does not disable reasoning), billed as output tokens by the provider, and perceived as annoying by users.

### Model Fleet Thinking Parameters

| Model | Provider | Thinking Default | Suppression Parameter | Can Disable? |
|-------|----------|------------------|----------------------|--------------|
| GLM-5.2 | Z.ai | Enabled | `thinking: { type: "disabled" }` | Yes |
| Kimi K2.5 | Moonshot | Enabled | `thinking: { type: "disabled" }` | Yes |
| Kimi K2.6 | Moonshot | Enabled | `thinking: { type: "disabled" }` | Yes |
| Kimi K2.7-Code | Moonshot | **Always on** | — | **No** (API rejects) |
| DeepSeek V4 | DeepSeek | Enabled | `thinking: { type: "disabled" }` | Yes |
| Qwen3.7-Plus | Alibaba | Enabled | `enable_thinking: false` | Yes |
| Qwen3-4B (self-hosted) | vLLM | Enabled | `enable_thinking: false` | Yes |
| MiniMax M2.5 | MiniMax | Enabled | `reasoning_effort: "none"` | Yes |

Three provider-specific parameter formats exist: `thinking.type` (GLM, Kimi, DeepSeek), `enable_thinking` (Alibaba/Qwen), and `reasoning_effort` (MiniMax, OpenAI).

---

## Avenue A: opencode `.well-known` Config

### What It Is

opencode supports org-wide configuration via `/.well-known/opencode` — a JSON endpoint served by our `librechat-opencode-wellknown` nginx chart. This is the **lowest-precedence** config source (local `opencode.json` overrides it), but it applies automatically to all authenticated users.

The config schema (`opencode.ai/config.json`) supports:
- **Per-model `options`**: Free-form object, passed through to the AI SDK as provider-specific params (e.g., `thinking`, `reasoning_effort`, `enable_thinking`)
- **Per-model `variants`**: Named presets (e.g., `"thinking"` variant with reasoning enabled). Users cycle via `ctrl+t`
- **Per-agent `options`**: Unrecognized fields pass through as model options

### How It Would Work

Add a `models` section under the `camer-digital` provider in `charts/librechat-opencode-wellknown/values.yaml`. Each model gets:
- `options` with thinking suppressed by default
- `variants.thinking` with thinking re-enabled (escape hatch)

Example (Strategy B — suppressed by default, opt-in via `ctrl+t`):

```yaml
# In values.yaml under camer-digital provider
models:
  glm-5p2:
    name: "GLM-5.2"
    reasoning: true
    options:
      thinking: { type: disabled }
    variants:
      thinking:
        thinking: { type: enabled }
  qwen3p7-plus:
    name: "Qwen3.7 Plus"
    reasoning: true
    options:
      enable_thinking: false
    variants:
      thinking:
        enable_thinking: true
  minimax-m2p5:
    name: "MiniMax M2.5"
    reasoning: true
    options:
      reasoning_effort: "none"
    variants:
      thinking:
        reasoning_effort: "high"
```

### Strategies

| Strategy | Behavior | Use When |
|----------|----------|----------|
| **A: Suppress all** | Thinking disabled, no variant to re-enable | Cost-critical, non-technical users, simple tasks |
| **B: Variants (default off)** | Thinking disabled by default, `ctrl+t` to re-enable | **Recommended** — balances cost and flexibility |
| **C: Per-agent** | Different `reasoningEffort` per agent definition | Granular control (e.g., architect=high, backend=low) |

### Advantages

- **Config-only**: YAML change in existing Helm chart, no code
- **Org-wide**: All opencode users get it automatically on next auth
- **Reversible**: Remove or modify the `models` section; ArgoCD reconciles
- **User agency**: `ctrl+t` variant cycling lets users opt back in for complex tasks
- **Existing precedent**: `lightbridge-code-intelligence` chart already has `review.extra` for the same purpose (currently empty)
- **Low blast radius**: opencode users only; well-known is lowest-precedence config (users can override)

### Disadvantages

- **opencode only**: Does not reach Kilo Code users, LibreChat users, or other clients
- **Lowest precedence**: Users can override via local `opencode.json` (by design — but means not enforced)
- **Per-model coverage**: Must enumerate every thinking-capable model (new models require a config update)
- **No runtime enforcement**: Cannot prevent a user from re-enabling thinking via `ctrl+t`

### When to Use

Use Avenue A when you want **a quick, org-wide default** for opencode users with minimal risk. This is the right starting point — it addresses the majority of users and can be shipped in days.

---

## Avenue B: Kilo Code `kilo.jsonc` Config

### What It Is

Kilo Code (kilo.ai, v7+) is an external AI coding agent platform rebuilt on opencode's codebase. Some users connect Kilo Code to our `camer-digital` gateway. Kilo has its own config file (`kilo.jsonc`) that does **not** fetch our `.well-known/opencode` endpoint — Avenue A changes do not reach Kilo users.

The config schema (`app.kilo.ai/config.json`) is nearly identical to opencode's: same `options`, `variants`, and `reasoning` fields. The suppression parameters are the same — Kilo is a thin layer over the same API.

### How It Would Work

Kilo users must apply thinking suppression in their own `kilo.jsonc` (project root or `~/.config/kilo/kilo.jsonc`). The config is identical to Avenue A's Strategy B:

```jsonc
// kilo.jsonc
{
  "$schema": "https://app.kilo.ai/config.json",
  "provider": {
    "camer-digital": {
      "npm": "@ai-sdk/openai-compatible",
      "options": { "baseURL": "https://api.ai.camer.digital/v1" },
      "models": {
        "glm-5p2": {
          "reasoning": true,
          "options": { "thinking": { "type": "disabled" } },
          "variants": { "thinking": { "thinking": { "type": "enabled" } } }
        }
        // ... same pattern for other thinking models
      }
    }
  }
}
```

### Kilo-Specific Features

Kilo has two additional capabilities not in opencode:

| Feature | What It Does | Limitation |
|---------|-------------|------------|
| `auto_collapse_reasoning: true` | Hides thinking blocks in the UI | Display only — reasoning tokens still consumed |
| `kilo-auto/efficient` tier | Routes simple tasks to non-thinking models automatically | Only works with Kilo's Auto Model feature |

### Advantages

- **Same params as Avenue A**: Identical `thinking`, `reasoning_effort`, `enable_thinking` fields
- **User control**: Kilo users manage their own config (no dependency on org deployment)
- **Variant cycling**: Same `ctrl+t` / `/variant` escape hatch

### Disadvantages

- **Not org-managed**: We cannot push config to Kilo users — each user must configure independently
- **Distributed maintenance**: Must document and maintain config guidance for users
- **Separate config file**: `kilo.jsonc` is distinct from `opencode.json`; users must know which they're using
- **No `.well-known` fetch**: Kilo ignores our org-wide endpoint entirely

### When to Use

Use Avenue B when **documenting guidance for Kilo-preferring users**. This is not a code change — it's a documentation task. Write a section in internal README/CONTRIBUTING showing the `kilo.jsonc` config, and optionally distribute a template via internal tooling.

---

## Avenue C: Gateway ExtProc Patch

### What It Is

The Envoy AI Gateway's ExtProc sidecar (`charts/core-gateway`) processes every request/response body inline. It currently handles token counting, cost CEL, model routing, and metadata. The ExtProc could theoretically inject thinking suppression parameters into request JSON bodies before forwarding to the upstream provider.

### How It Would Work

The ExtProc would:
1. Parse the incoming chat completion request body
2. Detect if the target model is a thinking-capable model
3. Inject the appropriate suppression parameter (`thinking.type: "disabled"`, `enable_thinking: false`, or `reasoning_effort: "none"`) into the request body
4. Forward the modified request to the upstream provider

Optionally, it could also strip `reasoning_content` from streaming SSE responses, preventing thinking output from reaching the client at all.

### Advantages

- **Central enforcement**: Applies to ALL gateway traffic regardless of client (opencode, Kilo, LibreChat, curl, etc.)
- **No user action required**: Users don't need to configure anything — thinking is suppressed at the infrastructure level
- **Per-user/org policies**: Could implement different thinking policies per user or organization (e.g., free tier = no thinking, paid tier = thinking enabled)
- **Response stripping**: Could remove `reasoning_content` from responses entirely, reducing both token cost and visible output

### Disadvantages

- **Go code required**: Not a config change — requires modifying the ExtProc source, which is Go code in a Helm-only repo
- **Critical path**: ExtProc is on the hot path for every request (ADR-0034). Adding body parsing increases latency and adds failure modes
- **High blast radius**: A bug in ExtProc affects ALL gateway traffic, not just opencode users
- **Provider-specific logic**: Different providers use different parameter formats (`thinking.type` vs `enable_thinking` vs `reasoning_effort`). The ExtProc must know which format to inject per model
- **SSE complexity**: Response stripping requires parsing streaming SSE chunks — non-trivial and error-prone
- **Maintenance burden**: Must be maintained alongside upstream ExtProc updates and new model additions
- **No escape hatch**: Users cannot opt back into thinking unless the gateway provides a per-request override mechanism

### When to Use

Use Avenue C when you need **central, non-overridable enforcement** — e.g., for LibreChat users who don't use opencode/Kilo, or when org policy requires thinking suppression regardless of client configuration. This is a future consideration, not a near-term action. The same effect is achievable for opencode/Kilo users via Avenues A+B.

---

## Comparison Matrix

| Criterion | A: `.well-known` | B: `kilo.jsonc` | C: Gateway ExtProc |
|-----------|-------------------|------------------|---------------------|
| **Reaches all clients** | opencode only | Kilo only | All clients |
| **Config-only** | Yes (YAML) | Yes (kilo.jsonc) | No (Go code) |
| **Org-managed** | Yes (automatic) | No (per-user) | Yes (automatic) |
| **User escape hatch** | `ctrl+t` variants | `ctrl+t` / `/variant` | None (unless built) |
| **Token savings** | High (per-model) | High (per-model) | Maximum (central) |
| **Quality control** | Configurable per-model | Configurable per-model | Configurable per-user/org |
| **Implementation effort** | Low (YAML in Helm chart) | Low (documentation only) | High (Go code + testing) |
| **Maintenance burden** | Low (central YAML) | Medium (user docs) | High (Go code + SSE parsing) |
| **Blast radius** | opencode users only | Kilo users only | All gateway traffic |
| **Risk** | Low (config, reversible) | Low (user config) | High (critical path) |
| **Time to ship** | Days | Hours (docs) | Weeks |
| **Existing precedent** | lightbridge-ci `extra` | None | None |

---

## Recommendation

### Primary: Avenue A — opencode `.well-known` config (Strategy B)

Ship Strategy B (thinking disabled by default, `ctrl+t` to re-enable):

1. **Lowest risk**: Config-only YAML change, no code, no gateway patches
2. **User agency**: Users can opt back into thinking via `ctrl+t` for complex tasks
3. **Immediate impact**: Eliminates reasoning tokens from output by default
4. **Existing precedent**: `lightbridge-code-intelligence` chart already has the `extra` lever pattern
5. **Reversible**: If quality degrades, remove the `models` section or change defaults

**Implementation steps:**
1. Add `models` section with thinking suppression to `charts/librechat-opencode-wellknown/values.yaml`
2. Run `helm lint` and `helm template` to verify rendering
3. Have @stephane-segning review model IDs and suppression parameters
4. Merge to main; ArgoCD reconciles ConfigMap; users get new config on next auth
5. Monitor gateway usage metrics for output token reduction
6. Iterate if users report quality degradation

### Secondary: Avenue B — Kilo Code documentation

Document the `kilo.jsonc` thinking suppression config in internal README/CONTRIBUTING. Users who prefer Kilo over opencode can apply the same suppression strategy locally. No Helm chart changes needed.

### Future: Avenue C — Gateway ExtProc

Consider only if central enforcement is needed for non-opencode/Kilo clients (e.g., LibreChat) or if org policy requires non-overridable thinking suppression. Requires Go code in ExtProc — separate effort with significant implementation and maintenance cost.

---

### Models Not Covered

`kimi-k2.7-code` (and `adorsys-frontend-pro` which routes to it) are intentionally omitted — the Moonshot API rejects `thinking.type: "disabled"` for this model.

---

## References

- **ADR-0014**: opencode `.well-known` config delivery mechanism
- **ADR-0034**: ExtProc design and constraints
- **Epic #143**: Runtime, deployment, and traffic management
- **opencode config schema**: [opencode.ai/config.json](https://opencode.ai/config.json)
- **opencode models docs**: [opencode.ai/docs/models](https://opencode.ai/docs/models/)
- **Kilo Code custom models**: [kilo.ai/docs/code-with-ai/agents/custom-models](https://kilo.ai/docs/code-with-ai/agents/custom-models)
- **Kilo Code auto model**: [kilo.ai/docs/code-with-ai/agents/auto-model](https://kilo.ai/docs/code-with-ai/agents/auto-model)
- **Provider-specific parameters**: Z.ai API ([docs.z.ai](https://docs.z.ai/api-reference/llm/chat-completion)), Moonshot API ([platform.moonshot.ai](https://platform.moonshot.ai/docs/api/chat)), DeepSeek API ([platform.deepseek.com](https://platform.deepseek.com/))
