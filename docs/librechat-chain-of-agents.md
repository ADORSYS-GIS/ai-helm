# LibreChat Chain-of-Agent Use Cases

A catalogue of multi-agent (Chain-of-Agent) patterns enabled by LibreChat,
produced by the brainstorm in ticket [**#414**](https://github.com/ADORSYS-GIS/ai-helm/issues/414)
(parent exploration story [#409](https://github.com/ADORSYS-GIS/ai-helm/issues/409)).

> **Scope:** ideation only — these are candidate patterns, not implementations.
> Each use case names the **agent combination** it requires and the **problem it
> solves**, satisfying the ticket's acceptance criteria.

## Shared contract

Every chain here follows two design rules that emerged across the brainstorm:

1. **Fenced-JSON artifact hand-off.** Each agent emits a small fenced JSON
   artifact that the next agent reads. This makes every stage's output
   inspectable (debuggable) and, crucially, **composable**: one chain's output
   is another chain's input (see UC5 → UC1 / UC2).
2. **A load-bearing human gate.** Every chain has a write step that is split
   behind a `dry-run` / write switch and isn't flipped without a human. This
   mirrors the repo's own governance doctrine: humans own intent and
   verification.

A recurring **limitation** finding: LibreChat chains are **linear** — they
cannot auto-loop. Where a true agent graph would retry on a quality-gate fail
(e.g. UC3's DoR Gatekeeper), the linear chain escalates open questions to the
human and re-runs. This is a key constraint to remember when designing chains.

---

## Use Case #1 — "Sprint-to-GitHub" ticket factory

**Goal:** turn an unstructured sprint dump into a correctly-structured,
governance-compliant set of GitHub issues (epics → stories → tickets),
deduplicated against what already exists and wired into a hierarchy — automating
the workflow we ran manually this session.

**Why a *chain* (not one agent):** the work is a sequence of hand-offs where each
stage refines the previous artifact (decompose → check conventions → dedup →
draft → create → verify). Specialised agents with narrow tool access are more
debuggable and safer than one mega-prompt.

### Inputs (kickoff payload)

| Field | Example | Purpose |
|---|---|---|
| `raw_input` | the sprint text/file | source of truth |
| `repo` | `ADORSYS-GIS/ai-helm` | read templates + create |
| `accountable_owner` | `@Koufan-De-King` | governance requires a human owner |
| `default_labels` | epic / user-story / ticket | match repo templates |
| `related_context` | "observability epic is #341" | seeds cross-referencing |
| `mode` | `dry-run` \| `create` | safety switch (see human gate) |

### Agents (sequential; each emits a fenced JSON artifact the next one reads)

1. **Decomposer** *(no tools)* — parse `raw_input` into a tree of
   `{temp_id, type, title, intent, parent_temp_id}`. No invented scope; every
   item traces to a line.
2. **Convention Loader** *(GitHub MCP: `get_file_contents`)* — fetch the repo's
   issue templates + `CLAUDE.md`; emit the required-fields schema + governance
   rules (Source-of-truth, Acceptance Criteria, Verification evidence, Human
   owner, AI Usage Declaration).
3. **Dedup & Cross-reference** *(search_issues, list_issues)* — classify each
   item **FOLD** (near-identical to an existing issue → don't create, cross-ref
   it) vs **CREATE** (distinct → record related issues to link). Stops duplicate
   sprawl.
4. **Drafter** *(no tools)* — write full template-compliant bodies using the
   schema + cross-refs.
5. **Creator** *(issue_write, sub_issue_write)* — *runs only when
   `mode=create`*; idempotency guard (skip if title already exists); capture
   each new issue's **numeric `id` AND `number`**; wire hierarchy with
   `sub_issue_write` (child = **`id`**, not number); post cross-ref comments
   for FOLD items.
6. **Verifier/Reporter** *(issue_read)* — read back, confirm fields + links
   resolved, produce a summary table.

### Human gate (load-bearing)

Split the chain at step 4/5: run 1→4 in `dry-run`, let the human review the
drafts, then flip `mode=create`. Issue creation is outward-facing and awkward to
undo; this mirrors the repo's own doctrine ("humans own intent and
verification").

### Caveats / findings

- **Projects v2 is a gap** — adding issues to an org Project needs `gh` + the
  `project` scope; the GitHub MCP exposes **no Projects v2 tools**. Workaround: a
  project **auto-add workflow** keyed on the labels the chain applies.
- **sub-issue `id` vs `number`** is the classic footgun — must be explicit in
  the Creator's instructions or wiring silently fails.
- **Leaner v1**: steps 2→4 and 6→5 can merge into a 4-agent chain; keeping them
  split makes per-stage failure observable — itself a finding (chain length ↔
  debuggability trade-off).

*Validated informally:* this is the exact pipeline a human+assistant executed to
create ~40 issues (#407–#419, #525–#547) on this repo, incl. dedup folds and
sub-issue wiring.

---

## Use Case #2 — Doc-drift remediation

**Goal:** detect where code/reality has diverged from docs **across many repos**,
draft the fix, self-review it, and open a PR. Directly attacks the rollout pains
in [#410](https://github.com/ADORSYS-GIS/ai-helm/issues/410) (docs going stale;
syncing docs across a large number of repos) — **the chain itself is the sync
mechanism.** Different shape from UC1: detection + judgment + write-back, not
CRUD.

### Inputs

`repos[]` (or org+filter) · `doc_globs` (`docs/**`, `*.md`) · `since`
(date/ref — bounds cost) · `truth_signals` (ADRs, CHANGELOG, commit/signature
changes) · `accountable_owner` · `mode` (`dry-run` | `propose-pr`)

### Agents

1. **Change Sensor** *(list_commits, get_commit, search_code)* — material
   changes since `since`.
2. **Doc Mapper** *(get_file_contents, search_code)* — map each change → the
   doc(s) that should describe it.
3. **Drift Detector** *(no tools)* — per pair, judge **in-sync / stale /
   missing**, citing the stale claim.
4. **Patch Drafter** *(no tools)* — minimal-diff corrected doc text, matching
   surrounding style.
5. **Doc Reviewer** *(no tools, adversarial)* — attack the draft: hallucinated?
   matches code? minimal? Reject/refine. **This self-review is the core
   multi-agent value-add.**
6. **PR Opener** *(create_branch, create_or_update_file, create_pull_request)*
   — *propose-pr only*; branch + PR citing findings. **Never commit to default
   branch.**

### Human gate

The **PR is the gate** — a proposal a human merges, never a direct push to
main.

### Findings

- Judgment-heavy → false positives; the adversarial Reviewer + PR-not-commit
  contains blast radius.
- Cross-repo = rate-limit/cost; mandatory `since` + batching.
- Anchor on **structured** truth signals (ADRs/CHANGELOG/signatures), not
  free-form diffs, to keep the detector honest.

---

## Use Case #3 — Ticket grooming (Definition-of-Ready)

**Goal:** turn a vague one-line ticket into a Definition-of-Ready ticket (clear
intent, cited source-of-truth, testable acceptance criteria, risks, scope).
Attacks the *tickets not well-defined* pain in
[#410](https://github.com/ADORSYS-GIS/ai-helm/issues/410). Inverse of UC1: UC1
creates *many* shallow tickets from a dump; UC3 deepens *one*.

### Inputs

`ticket_ref` (#532, or raw_text) · `repo` · `accountable_owner` · `mode`
(`dry-run` | `comment` | `edit-issue`)

### Agents

1. **Intent Clarifier** *(no tools)* — restate the real intent; list
   ambiguities/**open questions** blocking readiness.
2. **Context Gatherer** *(search_issues, search_code, get_file_contents)* —
   find source-of-truth (issues/ADRs/code) + load the template schema.
3. **Criteria Author** *(no tools)* — testable Given/When/Then criteria,
   negative/edge cases, out-of-scope.
4. **DoR Gatekeeper** *(no tools, checklist)* — score vs Definition-of-Ready
   (source-of-truth? testable? owner? no unverified claims?). Output **pass/fail
   + gaps**.
5. **Writer** *(issue_write update / add_issue_comment)* — *write modes only*;
   post enriched body as a comment or edit the issue.

### Human gate

The **DoR Gatekeeper** is the automated gate; a human approves before the Writer
edits a ticket.

### Findings

- **Linear chains can't auto-loop.** On a Gatekeeper fail, a true agent graph
  would loop back to the Clarifier; LibreChat chains are linear, so we
  **escalate the open questions to the human** and re-run. Key limitation
  finding for this ticket.
- Editing an existing ticket is destructive → default to `comment` mode.

---

## Use Case #4 — AI PR-review chain

**Goal:** review a PR for correctness + quality and post findings as review
comments, with a **swappable context stage** that plugs in the three arms of the
optimal-review epic [#407](https://github.com/ADORSYS-GIS/ai-helm/issues/407)
(raw file/PDF ingestion, knowledge-graph, or vector RAG). This makes UC4 a
concrete **delivery vehicle + benchmark harness** for #407 — swap strategy,
measure quality/cost/latency on the same PRs.

### Inputs

`pr_ref` (#542) · `focus` (correctness/security/style) · `context_strategy`
(none | files | graph | vector) · `accountable_owner` · `mode` (`dry-run` |
`post-review` | `comment-summary`)

### Agents

1. **Diff Ingestor** *(pull_request_read)* — diff, files, description, linked
   issues; chunk big PRs.
2. **Context Gatherer** *(search_code, get_file_contents + #407 backend)* —
   retrieve context per `context_strategy`. **The pluggable #407 stage.**
3. **Reviewer** *(no tools)* — findings with `file:line`, severity, rationale.
4. **Adversarial Verifier** *(no tools)* — drop hallucinated/low-confidence
   findings. **False positives are the #1 killer of AI review → load-bearing.**
5. **Poster** *(pull_request_review_write, add_comment_to_pending_review)* —
   *write modes only*; pending-review workflow (create → add inline → submit) or
   one summary. **Never approve/merge.**

### Human gate

The posted review is **advisory**; never auto-approve/merge. Default dry-run.

### Findings

- Context Gatherer is the quality lever **and** the tie to #407 — gives that
  epic a way to be measured in production.
- Inline comments require the pending-review workflow; big PRs need chunking.

---

## Use Case #5 — External-team "envoy" onboarding

**Goal:** point the chain at another team's repos; it assesses their AI-adoption
/ doc / ticket maturity and emits a tailored adoption plan. Ties to epic
[#342](https://github.com/ADORSYS-GIS/ai-helm/issues/342) (integrations with
external teams) and rollout story
[#410](https://github.com/ADORSYS-GIS/ai-helm/issues/410). It's a **meta-chain**:
its output can *feed UC1* (create the tickets) and *trigger UC2* (fix the stale
docs it found).

### Inputs

`team_repos[]` (or org+discover) · `dimensions` (docs freshness, ticket quality,
AI-tooling, test signals) · `output_target` (report | feed-uc1) ·
`accountable_owner` · `mode` (`dry-run` | `write-report`)

### Agents

1. **Repo Surveyor** *(search_repositories, list_commits, get_file_contents)* —
   inventory repos: languages, activity, README/docs/ADRs/CI/templates.
2. **Maturity Assessor** *(search_issues, search_code)* — score each dimension
   with evidence.
3. **Gap Synthesizer** *(no tools)* — prioritized gaps + concrete
   recommendations ("adopt /oc reviewer", "docs stale in X → run UC2", "tickets
   lack criteria → adopt template").
4. **Plan Author** *(no tools)* — the tailored plan; if `feed-uc1`, emit a
   **sprint dump in UC1's input shape** so the plan becomes tickets.
5. **Reporter / Hand-off** *(create_or_update_file, add_issue_comment)* —
   *write modes only*; write report + hand the UC1 payload onward.

### Human gate

A human reviews the plan before it feeds UC1. Writing into *another team's*
repos is socially loaded → **default to a report the envoy carries**, not
auto-filing in their repos.

### Findings

- **Chains compose** — UC5 → UC1 and UC5 → UC2. Strongest argument for the
  shared fenced-JSON artifact contract: a chain's output is another chain's input.
- Assessment is heuristic → present as **recommendations for a human**, never
  verdicts. Read-only by default; same cross-repo cost caveat as UC2.

---

## Cross-cutting findings

Applicable to **every** use case above:

- **Linear chains can't self-correct.** Loop-back (e.g. a quality gate failing
  → re-clarify) must be done by escalating to the human and re-running. This is
  the primary constraint of the LibreChat chain model and shapes how chains are
  segmented.
- **Adversarial verification is the core multi-agent value-add.** Wherever a
  chain produces a judgment-heavy artifact (UC2's draft, UC4's review), a second
  agent attacks it before it leaves the chain. Single agents hallucinate; the
  pair contains blast radius.
- **Human gates are load-bearing, not cosmetic.** Every write step is behind a
  `dry-run` / write switch and a human review. The doctrine: humans own intent,
  verification, and the irreversible action.
- **Tool access per agent = blast-radius control.** Agents without write tools
  simply cannot do damage; the agent that *can* write runs only in the chosen
  mode. Narrow tooling is part of the design, not a limitation.
- **Cross-repo runs cost.** Anything scanning many repos (UC2, UC5) needs a
  bounded `since` and batching against rate limits.
- **Projects v2 is a gap** in the GitHub MCP — there are no Projects v2 tools;
  compensate with label-keyed auto-add workflows.

## Most promising candidates (flagged for follow-up)

| Use case | Why it's high-value | Ties to |
|---|---|---|
| **UC1 — Sprint-to-GitHub factory** | Already validated informally (the ~40 issues #407–#419/#525–#547); automates a real, repeated manual workflow. | #409, #410 |
| **UC4 — AI PR-review chain** | Doubles as a **benchmark harness** for the optimal-review epic #407 — gives the pluggable context backend measurable production signal. | #407 |
| **UC5 — Envoy onboarding** | Demonstrates **chain composition** (UC5 → UC1 / UC2) and unblocks external-team integration. | #342, #410 |

UC2 and UC3 are individually valuable (attack concrete #410 pains) but lower
leverage than the three above; pursue them after UC1/UC4 land.

## Verification

This document **is** the verification evidence requested by ticket
[#414](https://github.com/ADORSYS-GIS/ai-helm/issues/414): a documented list of
use cases, each naming its agent combination and expected benefit, with the most
promising candidates flagged for follow-up.