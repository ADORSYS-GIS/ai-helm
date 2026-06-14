# ADR-0050: Let camer-digital-ai post AI reviews as a branded bot

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** @stephane-segning

## Context

ADR-0047 deliberately kept the `camer-digital-ai` GitHub App **auth-only**
(`metadata: read`): a key compromise on an App installed across many orgs must
not be able to write to anyone's code. The opencode CI review now authenticates
to the gateway through that App's OIDC binding (the LLM-side fix), but it still
**posts its review comment as `github-actions[bot]`** because the action posts
with the default `GITHUB_TOKEN`. The maintainer wants the review authored by the
**branded `camer-digital-ai[bot]`** — one identity for both "authenticate CI" and
"post the review."

A GitHub comment is authored by whatever token posts it; to post as the App, the
action must use an **App installation token**, which requires the App to hold
`issues: write` + `pull_requests: write`.

## Decision

Amend ADR-0047: grant `camer-digital-ai` **`issues: write` + `pull_requests:
write`** (in addition to `metadata: read`), and have CI post the review with an
**App installation token** (`actions/create-github-app-token`, app-id 3253522) so
the author is `camer-digital-ai[bot]`. Explicitly **do NOT** grant `contents`:

- The review **comment** is posted with the App token (Issues/PR write).
- CI **git** operations (clone/commit/push) keep using the workflow's own
  `GITHUB_TOKEN`, so the App needs no `contents` scope.
- The gateway/LLM auth is unchanged (the OIDC binding, ADR-0047).

Adoption: the App's private key is added as a GitHub Actions secret
(`CAMER_DIGITAL_AI_PRIVATE_KEY`); each existing install must re-approve the new
permissions (GitHub fires `installation` → `new_permissions_accepted`).

## Consequences

**Positive**
- Reviews are authored by one branded `camer-digital-ai[bot]` — the maintainer's
  goal; a single App covers both auth and reviewing.

**Negative**
- Wider blast radius: a private-key compromise can now spam **issue/PR comments**
  across **every** install (annoying, recoverable — not code). This reverses part
  of ADR-0047's minimal-scope posture; accepted deliberately.
- Every existing install (5 today) must re-approve the new permissions before its
  CI can post as the bot.

**Neutral / follow-ups**
- `contents` is still refused — code write is the catastrophic line. A future
  agent that must push code as the bot needs its own ADR before adding it.
- Needs the App private key as an Actions secret (org-level for reuse).

## Alternatives considered

- **Separate reviewer App** (keep camer-digital-ai auth-only) — rejected: the
  maintainer wants a single branded identity, not two Apps to manage.
- **Reuse the existing adorsys-gis CI/write-back App** — rejected: couples the
  reviewer identity to the GitOps-automation App.
- **Also add `contents: write`** — rejected: not needed (git push uses
  `GITHUB_TOKEN`); it's the catastrophic supply-chain scope.

## Related

- Amends: [ADR-0047](./0047-github-oidc-repo-binding-for-ci.md) (auth-only stance)
- Files: `.github/workflows/opencode.yml` (the app-token step); service repo
  `github-app-manifest.json` + `docs/github-app-permissions.md`
