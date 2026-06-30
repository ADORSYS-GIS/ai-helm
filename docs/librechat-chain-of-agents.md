# LibreChat Chain-of-Agent use cases

> Exploration for [#414](https://github.com/ADORSYS-GIS/ai-helm/issues/414) (under the LibreChat
> exploration story [#409](https://github.com/ADORSYS-GIS/ai-helm/issues/409)). These are candidate
> Chain-of-Agent (sequential, hand-off) workflows we can build on LibreChat agents over the GitHub MCP
> (already OAuth2-connected). The point of a *chain* over a single agent: the work is a sequence of
> hand-offs where each stage refines the previous one's artifact, and narrow per-agent tool access is
> more debuggable and safer than one mega-prompt.

## Conventions used by every chain

- Each agent emits a fenced ` ```json ` **artifact** as its last block; the next agent reads the **last
  JSON block** and ignores prose. This is how you get reliable hand-off in LibreChat (agents pass text).
- A **`mode`** input (`dry-run` vs an explicit write mode) gates every outward-facing write.
- A **human gate** sits before any irreversible/outward step — mirrors the repo doctrine: *humans own
  intent, verification, and consequences* (https://adorsys-gis.github.io/ai-governance/).
- Two agents recur across chains and are worth building once as a shared library: a **Convention/Template
  Loader** and a **Context / source-of-truth Gatherer**.

---

## LibreChat platform support (as of 2026-06)

How much of the above is buildable on LibreChat today, and where the seams are. **Short version: the
orchestration is config-provisionable; the agents and the chain wiring are still authored in the UI and
referenced by id.**

### Config-provisionable (`librechat.yaml` → `endpoints.agents`)
You can declaratively set capability gates and guardrails:

```yaml
endpoints:
  agents:
    disableBuilder: false        # gate the UI Agent Builder
    recursionLimit: 50
    maxRecursionLimit: 100
    capabilities:
      - 'chain'                  # enables Agent Chain (Mixture-of-Agents)
      - 'subagents'
      - 'tools'
      - 'actions'
      # … file_search, web_search, execute_code, ocr, etc.
    subagents:
      enabled: true
      allowSelf: true
      agent_ids:                 # allowlist of pre-built agents, by id
        - 'agent_context_gatherer'
        - 'agent_adversarial_reviewer'
```

### UI-only (not provisionable)
- **The agent definitions** (provider, model, instructions, tools) — built in the **Agent Builder**,
  stored in the **database**, then referenced by `id`.
- **The chain composition** itself — assembled in the UI. There is no documented "define the whole
  agent/chain in YAML" or JSON import.

### Two composition mechanisms (both relevant to the chains above)
| Mechanism | What it is | Maps to |
|---|---|---|
| **Agent Chain** | Mixture-of-Agents: a *sequence* of agents, each seeing prior outputs. **Max 10 steps, currently beta.** | The linear UC1–UC5 hand-off chains |
| **Subagents** | A parent agent spawns scoped children *as a tool call during its run* (the `agent_ids` allowlist). | The **reusable sub-agents** finding — Context Gatherer / Adversarial Reviewer as spawnable children |

### Ops implications (findings for #414)
- **No GitOps provisioning of the agent bodies.** Because agents live in the DB (not config),
  reproducing a chain across environments means rebuilding it in the UI (or a DB migration) — there is
  no declarative, version-controlled agent definition yet. This is the main blocker to "ship a chain as
  a product."
- **The 10-step / beta cap on Agent Chain** bounds chain length. UC1 (6 agents) and UC4 (5) fit; longer
  designs must either merge stages (the "leaner v1" note) or use Subagents for fan-out instead of more
  chain steps.
- **`subagents.agent_ids` is the closest thing to provisioning** — it pins *which* stable agent ids may
  compose, even though the agents themselves are UI-authored. Give shared sub-agents stable ids.

Sources: [agents config](https://www.librechat.ai/docs/configuration/librechat_yaml/object_structure/agents),
[Agent Chain](https://www.librechat.ai/docs/features/agents),
[Subagents](https://www.librechat.ai/docs/features/subagents).

---

## Use Case 1 — "Sprint-to-GitHub" ticket factory

**Goal:** turn an unstructured sprint dump into a structured, governance-compliant set of GitHub issues
(epics → stories → tickets), deduplicated against what already exists and wired into a hierarchy —
automating the workflow run manually to create ~40 issues this sprint (#407–#419, #525–#547).

### Inputs
| Field | Example | Purpose |
|---|---|---|
| `raw_input` | the sprint text/file | source of truth |
| `repo` | `ADORSYS-GIS/ai-helm` | read templates + create |
| `accountable_owner` | `@Koufan-De-King` | governance requires a human owner |
| `default_labels` | epic / user-story / ticket | match repo templates |
| `related_context` | "observability epic is #341" | seeds cross-referencing |
| `mode` | `dry-run` \| `create` | safety switch |

### Agents
1. **Decomposer** *(no tools)* — parse `raw_input` into a tree of `{temp_id, type, title, intent, parent_temp_id}`. No invented scope; every item traces to a line of input.
2. **Convention Loader** *(get_file_contents)* — fetch the repo's issue templates + `CLAUDE.md`; emit the required-field schema + governance rules (Source-of-truth, Acceptance Criteria, Verification evidence, Human owner, AI Usage Declaration).
3. **Dedup & Cross-reference** *(search_issues, list_issues)* — classify each item **FOLD** (near-identical to an existing issue → don't create, cross-ref it) vs **CREATE** (distinct → record related issues to link).
4. **Drafter** *(no tools)* — write full template-compliant bodies using the schema + cross-refs.
5. **Creator** *(issue_write, sub_issue_write)* — *`mode=create` only*; idempotency guard (skip if title exists); capture each new issue's numeric **`id` AND `number`**; wire hierarchy with `sub_issue_write` (child = **`id`**, not number); post cross-ref comments for FOLD items.
6. **Verifier/Reporter** *(issue_read)* — read back, confirm fields + links resolved, summary table.

### Human gate
Split at 4/5: run 1→4 in `dry-run`, human reviews the drafts, then flip `mode=create`.

### Caveats / findings
- **Projects v2 is a gap** — adding issues to an org Project needs `gh` + the `project` scope; the GitHub MCP exposes no Projects v2 tools. Workaround: a project **auto-add workflow** keyed on the labels the chain applies.
- **sub-issue `id` vs `number`** is the classic footgun — must be explicit or wiring silently fails.
- **Leaner v1**: merge 2→4 and 6→5 into a 4-agent chain; keeping them split makes per-stage failure observable (chain length ↔ debuggability trade-off).

---

## Use Case 2 — Doc-drift remediation

**Goal:** detect where code/reality has diverged from documentation across many repos, draft the fix,
self-review it, and open a PR. Directly attacks the rollout pains in
[#410](https://github.com/ADORSYS-GIS/ai-helm/issues/410): *docs not written frequently enough / falling
out of date*, and *problems syncing docs across a large number of repos* — **the chain itself becomes
the sync mechanism.** Shape differs from UC1: detection + judgment + write-back, not CRUD.

### Inputs
| Field | Example | Purpose |
|---|---|---|
| `repos` | `[org/a, org/b, …]` (or org + filter) | scope to sweep |
| `doc_globs` | `docs/**`, `README.md`, `*.md` | what counts as documentation |
| `since` | a date or git ref | bound the change window (cost control) |
| `truth_signals` | ADRs, CHANGELOG, commit messages, code signatures | structured ground truth to reduce hallucination |
| `accountable_owner` | `@handle` | PR ownership |
| `mode` | `dry-run` \| `propose-pr` | safety switch |

### Agents
1. **Change Sensor** *(list_commits, get_commit, search_code)* — gather material changes since `since` (merged PRs, new/changed files, new ADRs). Output: a changeset summary keyed by touched area.
2. **Doc Mapper** *(get_file_contents, search_code)* — map each changed area to the doc(s) that *should* describe it (path heuristics + content references). Output: `{change, candidate_docs[]}`.
3. **Drift Detector** *(no tools; reasons over fetched content)* — per pair, compare the doc section against the new reality and judge **in-sync / stale / missing**, citing the specific stale claim. Output: drift findings with severity.
4. **Patch Drafter** *(no tools)* — for each stale/missing finding, draft the corrected doc text as a **minimal diff** that matches surrounding style.
5. **Doc Reviewer** *(no tools; adversarial)* — critique the drafts: hallucinated? does the new text actually match the code/ADR? is it minimal? Reject/refine. **This self-review step is the core multi-agent value-add — it materially cuts hallucination.**
6. **PR Opener** *(create_branch, create_or_update_file, create_pull_request)* — *`propose-pr` only*; branch, apply edits, open a PR citing the findings. **Never commit to the default branch.**

### Human gate
The **PR itself is the gate** — output is a proposal a human reviews/merges, never a direct push to main.

### Caveats / findings
- Drift detection is judgment-heavy → false positives. The adversarial Reviewer + "PR not direct-commit" contains the blast radius.
- **Cross-repo cost**: the GitHub MCP is per-repo; the chain loops over `repos`. Many repos → rate limits and token cost; mandatory `since` filter + batching.
- **Ground truth**: comparing prose to code is fuzzy. Anchor on *structured* signals (ADRs, CHANGELOG, function/signature changes) rather than free-form diffs to keep the Drift Detector honest.

---

## Use Case 3 — Ticket grooming (Definition-of-Ready)

**Goal:** turn a vague one-line ticket into a Definition-of-Ready ticket (clear intent, cited
source-of-truth, testable acceptance criteria, risks, scope). Attacks the *tickets not well-defined*
pain in [#410](https://github.com/ADORSYS-GIS/ai-helm/issues/410). Closest in shape to UC1, but inverted:
UC1 creates *many* shallow tickets from a dump; UC3 deepens *one* ticket.

### Inputs
| Field | Example | Purpose |
|---|---|---|
| `ticket_ref` | `#532` (or `raw_text`) | the ticket to groom |
| `repo` | `ADORSYS-GIS/ai-helm` | context + write target |
| `accountable_owner` | `@handle` | accountability |
| `mode` | `dry-run` \| `comment` \| `edit-issue` | how to write back |

### Agents
1. **Intent Clarifier** *(no tools)* — restate the real intent in 1–3 sentences; list the ambiguities/assumptions that block readiness. Output: intent + **open questions**.
2. **Context Gatherer** *(search_issues, search_code, get_file_contents)* — find the source-of-truth (related issues, ADRs, code) and load the repo's ticket template schema. Output: cited context.
3. **Criteria Author** *(no tools)* — write testable Given/When/Then acceptance criteria, negative/edge cases, and explicit out-of-scope.
4. **DoR Gatekeeper** *(no tools; checklist)* — score the enriched ticket against a Definition-of-Ready checklist (source-of-truth present? criteria testable? owner set? no unverified AI claims?). Output: **pass/fail + gaps**.
5. **Writer** *(issue_write update / add_issue_comment)* — *write modes only*; post the enriched body as a comment or update the issue.

### Human gate
The **DoR Gatekeeper** is the automated gate; a human approves before the Writer edits an existing ticket. On a Gatekeeper **fail**, the chain surfaces the Clarifier's *open questions* to the human instead of guessing — see the loop note below.

### Caveats / findings
- **Linear chains can't auto-loop.** When the Gatekeeper fails (e.g. unanswered open questions), a true agent graph would loop back to the Clarifier. LibreChat chains are linear, so we **escalate to the human** (surface the open questions, re-run after answers) rather than auto-iterate. This is a real limitation finding for #414.
- Editing an existing ticket is destructive — prefer `comment` mode by default; reserve `edit-issue` for when the human has approved the rewrite.

---

## Use Case 4 — AI PR-review chain

**Goal:** review a pull request for correctness + quality and post the findings as review comments,
with a **swappable context stage** that plugs in the three arms of the optimal-review epic
[#407](https://github.com/ADORSYS-GIS/ai-helm/issues/407) (raw file/PDF ingestion, knowledge-graph
context, or vector RAG). This makes UC4 a concrete **delivery vehicle and benchmark harness** for #407:
swap the strategy, measure review quality/cost/latency on the same PRs.

### Inputs
| Field | Example | Purpose |
|---|---|---|
| `pr_ref` | `ADORSYS-GIS/ai-helm#542` | the PR to review |
| `focus` | correctness / security / style | scope the reviewer |
| `context_strategy` | `none` \| `files` \| `graph` \| `vector` | the #407 arm to use for context |
| `accountable_owner` | `@handle` | who owns the advisory review |
| `mode` | `dry-run` \| `post-review` \| `comment-summary` | safety switch |

### Agents
1. **Diff Ingestor** *(pull_request_read)* — fetch the diff, changed files, PR description, linked issues. Chunk by file/hunk for big PRs. Output: structured change set.
2. **Context Gatherer** *(search_code, get_file_contents; + the #407 backend)* — for each change, retrieve surrounding/related context using `context_strategy`. **This is the pluggable #407 stage.** Output: per-change context bundles.
3. **Reviewer** *(no tools)* — produce findings (correctness bugs, missing tests, security, convention violations), each with `file:line`, severity, rationale.
4. **Adversarial Verifier** *(no tools)* — challenge every finding: real, or a hallucination from missing context? Drop low-confidence ones. **False positives are the #1 killer of AI review, so this agent is load-bearing.**
5. **Poster** *(pull_request_review_write, add_comment_to_pending_review)* — *write modes only*; post survivors via the pending-review workflow (create pending → add inline comments → submit) or one summary comment. **Never approve or merge.**

### Human gate
The posted review is **advisory** — never auto-approve/merge. Default `dry-run`; a human triggers `post-review`.

### Caveats / findings
- The Context Gatherer is the quality lever **and** the explicit tie to #407 — UC4 gives that epic a way to be measured in production.
- Inline comments require the pending-review workflow, not loose comments.
- Large PRs blow the context window → chunk in the Ingestor; the context strategy bounds retrieval.

---

## Use Case 5 — External-team "envoy" onboarding

**Goal:** point the chain at another team's repos; it assesses their AI-adoption / doc / ticket maturity
and emits a tailored adoption plan. Ties to epic
[#342](https://github.com/ADORSYS-GIS/ai-helm/issues/342) (integrations with external teams) and rollout
story [#410](https://github.com/ADORSYS-GIS/ai-helm/issues/410). Crucially, it's a **meta-chain**: its
output can *feed UC1* (create the resulting tickets) and *trigger UC2* (fix the stale docs it found).

### Inputs
| Field | Example | Purpose |
|---|---|---|
| `team_repos` | `[org/x, org/y]` (or org + discover) | what to assess |
| `dimensions` | docs freshness, ticket quality, AI-tooling, test signals | scoring axes |
| `output_target` | `report` \| `feed-uc1` | report only, or emit a UC1-shaped payload |
| `accountable_owner` | `@handle` | the human envoy who carries the plan |
| `mode` | `dry-run` \| `write-report` | safety switch |

### Agents
1. **Repo Surveyor** *(search_repositories, list_commits, get_file_contents)* — inventory each repo: languages, activity, presence of README/docs/ADRs/CI/issue-templates. Output: per-repo profile.
2. **Maturity Assessor** *(search_issues, search_code)* — score each dimension with evidence: doc freshness (doc age vs code activity), ticket quality (well-formed?), AI-tooling presence (reviewer action / MCP?), test signals. Output: scored assessment.
3. **Gap Synthesizer** *(no tools)* — turn scores into prioritized gaps + concrete recommendations ("adopt the `/oc` reviewer", "docs stale in X → run UC2", "tickets lack acceptance criteria → adopt the template").
4. **Plan Author** *(no tools)* — produce the tailored plan; if `output_target=feed-uc1`, also emit a **structured sprint dump in the exact shape UC1's Decomposer expects**, so the plan becomes tickets.
5. **Reporter / Hand-off** *(create_or_update_file, add_issue_comment)* — *write modes only*; write the report and optionally hand the UC1 payload onward.

### Human gate
A human reviews the plan before it feeds UC1 (which then has its own gate). Writing into *another team's*
repos is socially loaded — **default to producing a report the envoy carries**, not auto-filing issues in
their repos.

### Caveats / findings
- **Chains compose** — UC5 → UC1 (create tickets) and UC5 → UC2 (fix docs). The strongest argument for the shared-artifact contract: chains can be piped.
- Assessment is heuristic + judgment → present as **recommendations for a human**, never verdicts (governance: humans own consequences). Especially across team boundaries.
- Same cross-repo cost/rate-limit caveat as UC2; read-only by default.

---

## Cross-cutting findings (for #414)

- **Reusable sub-agents.** A *Convention/Template Loader* (UC1 #2, UC3 #2) and a *Context / source-of-truth Gatherer* (UC2, UC3) recur — build them once as a shared library and compose.
- **The adversarial-reviewer pattern** (UC2 #5, UC4 #4) is the highest-leverage multi-agent move: a second agent whose only job is to attack the first's output measurably reduces hallucination. Worth standardising across chains that write.
- **Chains compose into pipelines.** UC5 feeds UC1 (assess team → create its tickets) and UC2 (assess team → fix its docs); UC4's context stage is itself the #407 review arms. Because every agent speaks the same fenced-JSON artifact contract, a chain's output is another chain's input — the biggest structural payoff of standardising the hand-off format.
- **Linear-chain limitation.** No native loops/branching → encode every decision as either a **human gate** or a **classify-and-route artifact the human acts on**, never an auto-loop. This bounds what Chain-of-Agents can do vs. a full agent graph — a key takeaway for the platform.
- **Write-safety pattern.** Every chain that mutates GitHub uses: `mode` switch → idempotency guard → human/PR gate → read-back verification. Standardise it.
- **Tooling gaps to track.** Projects v2 has no MCP tools (UC1); cross-repo sweeps hit rate limits and need `since`/batching (UC2).

## Status / next

- Five use cases developed (UC1 ticket factory, UC2 doc-drift, UC3 ticket grooming, UC4 PR-review, UC5 envoy); each is also captured as a comment on #414.
- Natural follow-ups: build the **shared sub-agent library** (Template/Convention Loader, Context Gatherer, Adversarial Reviewer) so the chains compose cleanly; pick **one chain to prototype end-to-end** on a low-stakes repo (UC3 ticket grooming is the safest first build — single ticket, `comment` mode, no cross-repo sweep).
