---
name: governance
description: Use when creating or editing any of these five artifact types in the ADORSYS-GIS/ai-helm repository: Epic (GitHub issue), User Story (GitHub issue), Dev Ticket (GitHub issue), Pull Request, or Architecture Decision Record (ADR). This skill instructs the agent to fetch and apply the ADORSYS-GIS AI governance templates from https://adorsys-gis.github.io/ai-governance/ before producing any artifact, ensuring each type uses its correct template. Also apply when reviewing whether an existing issue, PR, or ADR matches the governance format.
compatibility: opencode
---

# AI Governance — Artifact Templates

All artifacts in this repository (GitHub issues, pull requests, and ADRs) must
follow the ADORSYS-GIS AI Governance templates. This skill tells you where each
template lives and what you must do before producing any artifact.

**Governance source of truth:** https://adorsys-gis.github.io/ai-governance/

---

## The one rule

> **Before drafting any artifact, fetch the relevant template below. Do not
> invent sections not present in the template. Do not omit required sections.**

---

## Template index

### 1. Epic (GitHub issue)

**When:** the work is large, spans multiple tickets, and represents a meaningful
business or technical objective.

**GitHub form:** `.github/ISSUE_TEMPLATE/epic.yml` (auto-applied when opening
an issue with the Epic type — used as reference for section names).

**Governance page:** https://adorsys-gis.github.io/ai-governance/

**Required sections** (in order):
- Executive Summary — *We want to [outcome] because [reason]. This epic exists
  to solve [the real problem].*
- Strategic Intent — 1–3 sentences; a person must be able to say this verbally.
- Problem Statement — current pains + impact on users / ops / business.
- Desired Outcome — what is observable when this epic is complete.
- Scope (In / Out) — anything not listed must be clarified before implementation.
- Source of truth (links) — full URLs or #123. No source of truth = not ready.
- Stakeholders — Product Owner, Tech Lead, Delivery Owner, Security/Compliance.
- Key Assumptions — each must be validated or converted to a risk before delivery.
- Constraints — technical, security, compliance, timeline, dependency, operational.
- Risks — Risk / Probability / Impact / Mitigation.
- Success metrics — Metric / current / target / source (outcomes, not activity).
- Child User Stories — each must have its own AC and verification evidence.
- Human accountable owner — @github-handle / Name (required).
- AI Usage Declaration — select all that apply (required).
- Human verification checkboxes — the accountability box is required.

---

### 2. User Story (GitHub issue)

**When:** the work describes a user need or a valuable capability.

**GitHub form:** `.github/ISSUE_TEMPLATE/user-story.yml`

**Governance page:** https://adorsys-gis.github.io/ai-governance/

**Required sections** (in order):
- Story Statement — *As a [user], I want [capability], so that [benefit].*
- Real Intent — why this story matters (not a copy of an AI-generated summary).
- Background and Context — current behavior, limitation, and pain.
- Source of truth (links) — required; missing source of truth = not ready.
- Acceptance Criteria — Given/When/Then, negative/edge cases, non-functional.
- Out of Scope — explicit exclusions.
- Dependencies and Blockers.
- Assumptions.
- Implementation Notes — guidance, not unquestionable truth.
- Test Expectations.
- Verification evidence — required; no evidence = not done.
- Human accountable owner — required.
- AI Usage Declaration — required.
- Human verification checkboxes — accountability box required.

---

### 3. Dev Ticket (GitHub issue)

**When:** implementation work, bugs, refactors, technical tasks, spikes, or
operational work.

**GitHub form:** `.github/ISSUE_TEMPLATE/dev-ticket.yml`

**Governance page:** https://adorsys-gis.github.io/ai-governance/

**Required sections** (in order):
- Type — Feature / Bug / Refactor / Technical debt / Spike / Security /
  Performance / Documentation / Operational task (required dropdown).
- Summary — *We need to [do what] because [why]. Expected result: …*
- Intent — the real intention; if you cannot explain it, the ticket is not ready.
- Source of truth (links) — required; no source of truth = must be challenged.
- Current Behavior — with evidence (logs, screenshots, metrics).
- Expected Behavior — how the system should behave after this ticket.
- Acceptance Criteria — Given/When/Then, error cases, no regressions, tests added.
- Out of Scope.
- Technical Context — relevant files, services, constraints.
- Risks.
- Test Plan — unit / integration / e2e / manual / regression / security commands.
- Verification evidence — required.
- Human accountable owner — required.
- AI Usage Declaration — required.
- Human verification checkboxes — accountability box required.

---

### 4. Pull Request

**When:** any code or configuration change is being merged.

**GitHub template:** `.github/PULL_REQUEST_TEMPLATE.md` (auto-applied by GitHub
when opening a PR — used as reference for section names).

**Governance page:** https://adorsys-gis.github.io/ai-governance/

**Required sections** (in order):
1. Summary — bullet list of changes; what problem/ticket it solves.
2. Intent — why this change exists.
3. Scope — In Scope / Out of Scope lists.
4. Verification — checklist + commands run + results (paste or link).
5. Screenshots / Evidence — screenshot, logs, metrics, or recording links.
6. Risk Assessment — Low / Medium / High + risks + mitigations.
7. AI Usage Declaration — select all that apply + human verification checklist.
8. Reviewer Focus — select the review dimensions that matter for this PR.

---

### 5. Architecture Decision Record (ADR)

**When:** a significant architectural or technical decision is being recorded.

**Local template:** `docs/adr/template.md` — copy it to
`docs/adr/<NNNN>-<short-title>.md` and fill in the sections.

**Naming convention:** `ADR-NNNN` where NNNN is the next available number in
`docs/adr/README.md`.

**Required sections** (in order):
- Header — `# ADR-NNNN: <short imperative title>` with Status / Date / Deciders.
- Context — 3–6 sentences on the situation forcing the decision.
- Decision — what was chosen, stated as imperative ("Adopt X", "Replace Y with Z").
- Consequences — positive, negative, and neutral/follow-ups. Be honest.
- Alternatives considered — for each rejected option: what it was, why it lost.
- Related — commit SHA, docs, charts/files touched, supersedes/superseded-by.

> ⚠️ **ADRs are immutable once Accepted.** To change a decision, write a new
> ADR that supersedes the old one — do not edit the original body.

---

## Hard rules (apply to all artifact types)

1. **Fetch before you draft.** Visit the governance page or the local template
   file before producing the artifact. Do not work from memory.
2. **No invented sections.** Do not add headings not present in the template.
3. **No omitted required sections.** Every section marked required must be
   present, even if the answer is "N/A — not applicable because …".
4. **AI Usage Declaration is mandatory on every artifact.** Fill it in honestly.
5. **Human accountable owner is mandatory on issues.** It must be a real person
   (@github-handle), not "the team" or "TBD".
6. **Source of truth must be linked.** No source of truth = the artifact is not
   ready. Do not proceed without it.
7. **Blank issues are disabled.** GitHub enforces this via `blank_issues_enabled:
   false` — always use the appropriate issue form.

---

## Review checklist (when checking an existing artifact)

- [ ] Correct template type used (Epic ≠ Story ≠ Ticket).
- [ ] All required sections present and non-empty.
- [ ] Source of truth linked (URL or #issue).
- [ ] AI Usage Declaration filled in.
- [ ] Human accountable owner named.
- [ ] Verification evidence provided (issues) or commands/results present (PRs).
- [ ] ADR: status is set; if Accepted, body is not being edited inline.
