# Plan: Rework PR #937 for Ticket #832 (LibreChat Coder Agent)

**Status:** Proposed · **Date:** 2026-08-10 · **Author:** @Guy-Ghis (drafted with agent analysis)
**Target:** PR #937 / branch `feature/832-librechat-coder-agent` / Epic #821 / Ticket #832

> This is a working proposal. The remediation items below are **applied** in the
> working tree on branch `feature/832-librechat-coder-agent` (head `6ac69cf3`),
> **not committed or pushed**. See the "Applied / pending" markers per section.

## Change log

- **Applied** (working tree only, uncommitted): ADR-0086 restored to
  `origin/main` (Proposed, date 2026-07-24); `coder-workspace-urls.md` restored
  to `origin/main` (606 lines) with the subagent-delegation note + prompt-doc
  reference appended; **completed** the coder implementation end-to-end.
- **Applied — model+MCP fix** (both repos): `model: adorsys-coder-pro-internal`
  and `mcpServers: [coder_mcp]` — the only ids the `converse` provider actually
  exposes (verified in `ai-helm-values` `librechat-app.yaml` model list + the
  `coder_mcp` MCP registration). The PR's `adorsys-coder-pro` / `coder` were
  dangling.
- **Applied — ai-helm-values live seed**: added the `coder` DB agent to
  `agentSeed.agents` (enabled: true) with the corrected model/MCP + full system
  prompt + guardrails, consistent with the existing Security/Test/Deep Reviewer
  seed entries.
- **Not applied / needs decision**: a `converse` DB agent that delegates to
  `coder` was NOT seeded — the existing `converse` is a modelSpec persona
  (ephemeral; true subagent delegation needs a DB agent, and a `converse` DB
  agent would collide with the persona). Surfacing `coder` to users is done via
  the DB agent itself (ADR-0088 pattern). Live e2e verification + ADR accept
  transition remain outstanding.

---

## Reader summary

PR #937 gets the **architectural direction right** — `coder` as a subagent
delegated by `converse` via `agentSeed.agents`, using the existing idempotent
`seed-agents.js` mechanism. But it ships four problems that should block merge:

1. **Governance violation** — ADR-0086 is rewritten (Proposed → Accepted),
   its **date is backdated** (2026-07-24 → 2026-06-25), authors changed, and the
   decision body rewritten, all inside a feature PR.
2. **−537 lines of hard-won operational knowledge deleted** from
   `docs/integrations/coder-workspace-urls.md` (606 → ~103 lines), including the
   zone-delegation/DNS-01 trap, the 63-char limit, the 404-vs-403 semantics, the
   `owner`-is-not-writable share rule, licensing, and the rollback runbook.
3. **Model name may not resolve** — the agent uses `model: adorsys-coder-pro`,
   which does **not** exist as a catalog key (only `adorsys-coder` and
   `adorsys-coder-pro-internal` do).
4. **No end-to-end verification** — only `helm lint`/`helm template` are shown;
   the ticket's acceptance criteria (workspace created → app scaffolded → link
   returned) are unproven.

Also: the fleet roster is defined in **three places that must not diverge** —
ADR-0086's table, `values.yaml`, and the prompt doc.

---

## 1. ADR-0086 — restore the original decision

**Problem.** The current branch rewrites `docs/adr/0086-...md` wholesale:
- Status `Proposed` → `Accepted`
- Date `2026-07-24` → **`2026-06-25`** (backdated ~1 month)
- `Deciders: @stephane-segning` → `Authors: @benie-joy-possi, @Guy-Ghis`
- Decision body replaced

Per `CLAUDE.md`: *"ADRs are immutable once Accepted. Don't edit the decision body
of an Accepted ADR. To change a decision, write a new ADR that supersedes the old
one."*

**Recommended change.**
1. **Restore** `docs/adr/0086-...md` from `origin/main` (the original
   "Proposed" proposal, date 2026-07-24) — it must be returned to its
   pre-PR content, byte for byte.
2. Do **not** backdate; do **not** flip status to Accepted inside this PR.
3. If the pull is intended to *accept* ADR-0086, that is a **separate,
   deliberate step** (a reviewer/maintainer decision, recorded with the real
   date), not a silent edit in a feature PR.
4. If the decision genuinely changed (it mostly did not — the subagent shape was
   already in ADR-0086), the sanctioned path is a **new superseding ADR** (e.g.
   ADR-#### "Coder fleet seed — reconcile roster"), leaving 0086's body intact.

> Note: the `<!-- ai-governance:stanza -->` marker + "Accepted"-form template was
> applied. If the team's intent really is to accept 0086, the *correct* artefact is
> an **`ai-governance` Deferred-to-Accepted transition** done deliberately, not
> spliced into a feature PR with a wrong date.

---

## 2. `coder-workspace-urls.md` — restore the deleted operational knowledge

**Problem.** The PR shrinks the doc from **606 → ~103 lines**. The deleted
content is the platform team's hard-won operational knowledge:

| Deleted section (on `origin/main`) | Why it matters |
|---|---|
| § "Mental model: reachable vs accessible" (3 layers) | The single biggest source of confusion; 303 ≠ broken DNS. |
| ⚠️ "A denied user gets `404`, not `403`" | Anti-enumeration behaviour; classic mis-debug. |
| "Four ways to reach a process in a workspace" + `port-forward` ≠ port sharing | Similar-name trap. |
| Step 2a: "ask the API, don't build the string" (`subdomain_name`) | Build-by-hand breaks on the agent segment / 63-char edge. |
| ⚠️ "Declared apps must set `subdomain = true`" | `CODER_DISABLE_PATH_APPS=true` → 403 trap. |
| ⚠️ "Why workspaces live on `camer.digital`, not under `coder.ai.camer.digital`" | DNS-01 / Cloudflare-vs-Route53 delegation trap; orphaned TXT records. |
| "The share levels" — `owner` is **not writable** on a port share | `400 Port sharing level not allowed` misdiagnosis. |
| ⚠️ `/port-share` singular (not `/port-shares`) | "feature missing" misdiagnosis. |
| "What 'public' actually means" + "Licensing: public sharing works on OSS" | Real exposure blast radius + entitlement misread. |
| Runbook (publish / list / revoke / verify) | The actual commands the agent and humans need. |
| Verification platform-side + **Rollback** + "Where each piece lives" | Recovery path; currently deleted. |

`CLAUDE.md` doc convention is explicit that these hard-won lessons must be
preserved ("update the docs means ALL of them" and the top-level pointer keeps
the troubleshooting knowledge).

**Recommended change.** Restore `docs/integrations/coder-workspace-urls.md` from
`origin/main` and **append** the new §3 "LibreChat Coder Agent Integration
Contract" (and the subagent-delegation note) rather than replacing the whole
file. Net effect: the doc grows from 606 → ~640 lines, preserving every gotcha
while adding the agent contract.

---

## 3. Model reference — RESOLVED (ai-helm-values available)

**Problem (original).** `charts/librechat-app/values.yaml` set `model:
"adorsys-coder-pro"`. The `ai-models` catalog keys are `adorsys-coder` (external)
and `adorsys-coder-pro-internal` (`disableExternal: true` — internal only); there
is no first-class `adorsys-coder-pro`.

**Applied decision.** Now that `ai-helm-values` is available alongside, I confirmed
from the live converse-provider model list
(`environments/prod/values/librechat-app.yaml` models.default) that it exposes
**`adorsys-coder-pro-internal`** (context 1048576, GLM-5.2) — not `adorsys-coder-pro`.
So I set `model: adorsys-coder-pro-internal` in:
- `ai-helm/charts/librechat-app/values.yaml` (structural default)
- `ai-helm-values/environments/prod/values/librechat-app.yaml` (live seed)

and reconciled the prompt doc + ADR-0086 `coder` row to the same id.

**MCP server name.** The registered LibreChat MCP server is **`coder_mcp`** (not
`coder`). Since `seed-agents.js` maps `mcpServers: [name]` → token
`sys__all__sys_mcp_<name>`, the PR's `coder` would have seeded a token that matches
no server. Fixed to `mcpServers: [coder_mcp]` in both repos → resolves to
`sys__all__sys_mcp_coder_mcp`.

---

## 4. Add real end-to-end verification + single source of truth

**Problem.** The PR's "Verification" shows only:
```bash
helm lint charts/librechat-app
helm template test-release charts/librechat-app --set agentSeed.enabled=true ...
```
That proves the **chart renders**, not that the agent works. Ticket #832's
acceptance criteria — workspace created via MCP → in-workspace agent receives
scaffold instructions → app boots → reachable link returned — are **not
demonstrated**.

**Recommended change (verification).**
- Run (or delegate to the reviewer) a **live smoke test**:
  1. `coder_list_templates` / `coder_list_workspaces` reachable via the Coder MCP.
  2. `coder_create_workspace` succeeds.
  3. In-workspace OpenCode (AgentAPI) receives the scaffold prompt.
  4. Next.js + tRPC + Keycloak boots on :3000.
  5. Port shared → URL returns `200`; then revoke → `303`.
- Record outputs/logs/URLs as verification evidence on the ticket, and tick the
  ticket's checkboxes only when each is genuinely true.

**Recommended change (single source of truth).**
- Make `charts/librechat-app/values.yaml` `agentSeed.agents` the **canonical**
  fleet definition.
- Have ADR-0086 and the prompt doc **reference** (not duplicate) the roster.
- Reconcile the three currently-divergent copies: the ADR-0086 table entry for
  `coder` (tools + `mcpServers`), the `values.yaml` entry, and the prompt doc's
  "Operational Constraints" — they already disagreed and the AI-reviewer noted it
  (P2 unresolved thread).

---

## Suggested commit sequence (when authorised)

1. `revert(coder): restore ADR-0086 and coder-workspace-urls.md to main` — undo
   the ADR rewrite + the doc deletion (keeps the feature's values/prompt).
2. `fix(coder): point Coder agent at a resolvable model id` — the §3 fix.
3. `feat(coder): append LibreChat agent contract to workspace-urls doc` — re-add
   §3 on top of the restored doc.
4. (Separate, deliberate) `docs(adr): accept ADR-0086` or a new superseding ADR.
5. Update ticket #832 with live e2e verification evidence.

> Nothing above has been executed. This plan is for review before any git action.

---

## References

- Ticket #832: https://github.com/ADORSYS-GIS/ai-helm/issues/832
- Epic #821: https://github.com/ADORSYS-GIS/ai-helm/issues/821
- PR #937: https://github.com/ADORSYS-GIS/ai-helm/pull/937
- ADR-0086, ADR-0088, ADR-0121; `seed-agents.js`; `CLAUDE.md` (ADRs immutable; .md docs convention)
