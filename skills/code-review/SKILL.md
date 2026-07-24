---
name: code-review
description: A structured procedure for reviewing a code change (pull/merge request) — what to evaluate, how to grade findings on the P0–P3 severity framework, and how to phrase feedback. Use when reviewing a diff, a PR, or deciding whether a change is ready to merge.
---

# Code Review

Find what humans miss — real bugs, security flaws, broken assumptions, gaps in
reasoning — *before* they reach production, without holding a net improvement
hostage over nits. You are a skeptical senior engineer and a security reviewer
in one, and an assistant, not a gatekeeper: a human owns the merge decision.

## The one rule

> There is no perfect code, only *better* code. **Endorse a change once it
> clearly improves the health of the codebase**, even if it isn't perfect. Be
> adversarial in *finding* problems; be constructive in the *verdict*.

Forward progress with sound code health beats endless polishing. Never wave
through something that makes the codebase worse; never block a net improvement
over P3s.

## Prime directives (apply throughout)

1. **Review THIS change, not the repository.** The diff is the subject; the rest
   of the repo is only context. A problem in code this change doesn't touch is
   **not a finding** — at most one terse "pre-existing, consider a separate fix"
   note, never a P0/P1. Reviewing the repo instead of the change is the most
   trust-destroying failure mode.
2. **Cite or don't claim.** Every finding names the concrete failure mode (the
   input/path that triggers it) and points at the exact lines. If you can't cite
   it, don't raise it.
3. **A wrong finding costs more trust than a missed nit.** Default to adversarial
   *investigation*, not invention. Don't manufacture findings to look thorough,
   and don't rubber-stamp — the cure for a lazy "looks fine" is to actually read
   each changed file, not to pad the list.
4. **Security is a mandatory dimension of every review** — not an optional
   section. On every change ask "what could a malicious actor do with this?"
   (authz on new/changed endpoints, untrusted input reaching a dangerous sink,
   secrets/credentials, trust-boundary crossings) even when the change isn't
   framed as security. A proven security flaw is **P0**; a plausible one is at
   least **P1**.

## Severity — grade every finding P0–P3

Label each finding so the author knows what blocks merge:

- **P0 — critical, must fix before merge.** Security flaws (injection, auth
  bypass, secrets in code/logs, data loss/corruption) **and serious "future
  code" risks** — a design or decision that will be very costly to undo or that
  endangers the codebase's health going forward. Blocks merge.
- **P1 — bad, should fix.** Wrong implementations, logic/thinking errors, broken
  assumptions, incorrect behavior on real inputs/edge cases. Fix before merge, or
  defer only with an explicit, justified reason.
- **P2 — medium.** Notable maintainability, robustness, or quality issues that
  will bite a maintainer or a failure path — worth fixing, not a blocker.
- **P3 — might fix (mergeable as-is).** Nits, style, naming taste, minor polish.
  Author's discretion; **never blocks**.

Calibration rules:
- **Grade on evidence, not vibes.** A confirmed issue is recorded even at P2/P3;
  an unprovable "what if" is at most a P3 question — or nothing.
- **Don't inflate to look useful, don't bury a blocker among nits.** A precise
  three-finding review beats a noisy ten-finding one.
- If a review has **only P3s**, approve and let the author decide.

## Review in this order (risk-first)

1. **Purpose** — is *this* change wanted? Read the description/linked issue/ADR
   before the diff. If it shouldn't exist, say so before reviewing lines.
2. **Design** — does it fit the architecture, or bolt on a parallel way of doing
   the same thing? Flag a fundamental design problem *now*, before nits, so the
   author isn't building on a flawed base. (Serious design risk = P0 "future
   code"; smaller ones = P2.)
3. **Correctness** — trace old→new per hunk. Off-by-one/boundaries; null/empty;
   inverted/missing conditions; wrong operator; missing return/break; illegal or
   inconsistent states. Does the code match the stated intent?
4. **Security** — the mandatory dimension above.
5. **Concurrency & errors** — races, lost updates, locks held across await/IO;
   swallowed errors, partial failure with no rollback, resource leaks.
6. **Data & compatibility** — schema/migration safety, backward/forward compat,
   irreversible or data-losing operations, breaking API changes.
7. **Tests** — is the change actually covered? Do tests assert behavior (not just
   run) and exercise the failure modes, not only the happy path?
8. **Maintainability** — duplication that should reuse a helper, wrong-layer
   abstraction, misleading names, YAGNI/speculative generality, comments that
   explain *what* not *why*, docs not updated when a contract changed.

## How to phrase feedback

- **Comment on the code, not the coder** — "this can NPE on empty input", not
  "you forgot the empty case".
- **Explain *why*** and prefer suggesting a direction (or the exact fix when
  that's fastest) over prescribing — the why is what teaches and survives in the
  thread.
- **Acknowledge genuinely good work specifically** — it's calibration, not
  flattery, and tells the author what to keep doing.
- If code is unclear, ask the author to **clarify the code** (or add a comment),
  not just to explain it in the thread — the next reader won't have the thread.
- Don't nitpick what a linter/formatter already enforces.

## Handling disagreement

1. Reach consensus on facts first (benchmark, cite the standard, point at the
   code). The author may be right — be willing to be convinced.
2. If stuck, escalate to the maintainer rather than letting the change rot or
   wearing the author down. Resolve with facts or a decision-maker.

## Definition of done (approve when all true)

- [ ] Purpose justified (issue/ADR/source-of-truth linked).
- [ ] Design fits; no obviously simpler approach.
- [ ] Correct for the edge/failure cases you actually checked.
- [ ] Security impact assessed and stated (even if "no new surface").
- [ ] Tests exist and would fail if the change broke.
- [ ] **No unresolved P0/P1.** (P2/P3 may remain at the author's discretion.)
- [ ] Docs updated where a behavior/contract changed.
- [ ] Net effect: the codebase is healthier than before.
