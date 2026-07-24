---
name: Code Review
description: A structured procedure for reviewing a code change (pull/merge request) — what to evaluate, how to calibrate severity, and how to phrase feedback. Use when reviewing a diff, a PR, or deciding whether a change is ready to merge.
---

# Code Review

A good review makes the codebase healthier over time without blocking progress
for perfection. Approve once the change **definitely improves overall code
health**, even if it isn't perfect. Inspired by Google's engineering practices,
restructured into an actionable checklist.

## The one rule

> Reviewers should favor approving a change once it improves code health, even if
> it is not perfect. There is no "perfect" change — there is only *better*.

Balance forward progress against the value of each improvement you request. Do
not let the perfect block the clearly-good.

## Review in this order

1. **Purpose** — Does the change make sense? Is *this* change actually wanted?
   Read the description and the linked issue/ADR before the diff. If the change
   shouldn't exist, say so before reviewing lines.
2. **Design** — Does it belong here? Does it fit the architecture? Do the
   interactions with the rest of the system make sense? This is the most
   important thing to get right — and the hardest to change later.
3. **Functionality** — Does it do what it claims, and is that good for users
   (including future developers)? Think about edge cases, concurrency, and
   failure modes, not just the happy path.
4. **Complexity** — Is it more complex than it needs to be? Could a future dev
   understand and use it easily? Watch for over-engineering (solving problems
   that don't exist yet).
5. **Tests** — Are there appropriate tests, and do they actually exercise the
   change? Tests should fail when the code is broken. No dead or always-green
   tests.
6. **Naming & comments** — Clear names? Comments explain *why*, not *what*
   (the code shows what). Stale comments removed.
7. **Consistency & style** — Follows the project's conventions and the local
   file's style. Style nits are `Nit:` unless they violate an agreed standard.
8. **Docs** — Are relevant docs (README, ADRs, runbooks) updated when behavior
   or contracts change?

## Severity — label every comment

Prefix each comment so the author knows what blocks merge:

- **`Blocking:`** — must be fixed before merge (correctness, security, data
  loss, a broken contract, missing critical test).
- **`Nit:`** — minor / optional; author's discretion (style, naming taste, a
  cleaner phrasing). Never block on a nit.
- **`Question:`** — you don't understand something; the answer may or may not
  change anything.
- **`FYI:`** — non-actionable context for the future; not for this change.

If a review has **only** nits, approve and let the author decide.

## How to phrase feedback

- Comment on the **code, not the coder** — "this function can NPE on empty
  input", not "you forgot to handle empty input".
- Explain **why**, and prefer suggesting a direction over prescribing the exact
  line. Give the reasoning so the author learns, not just the fix.
- Offer sincere praise for good decisions — reviews aren't only for finding
  faults.
- If something is unclear, ask the author to **clarify the code** (or add a
  comment), rather than only explaining it to you in the thread. The next reader
  won't have the thread.

## Handling disagreement

1. Reach technical consensus on facts first (benchmark, cite the standard, point
   at the code).
2. The author may be right — be willing to be convinced.
3. If stuck, escalate to the team/maintainer rather than letting the change rot
   in review. Never wear someone down; resolve with facts or a decision-maker.

## Speed

- Review promptly (within one business day where you can) — a fast-moving review
  loop is worth more than a perfectly-thorough-but-slow one.
- If you can't do a full review now, a quick "looks reasonable, will look
  deeper by X" unblocks the author's mental context.

## Definition of done (approve when all true)

- [ ] The change's purpose is justified (issue/ADR/source-of-truth linked).
- [ ] Design fits the system; no simpler approach is obviously better.
- [ ] Correct for the edge/failure cases you can think of.
- [ ] Tests exist and would fail if the change broke.
- [ ] No unresolved `Blocking:` comments.
- [ ] Docs updated where behavior/contracts changed.
- [ ] Net effect: the codebase is healthier than before.
