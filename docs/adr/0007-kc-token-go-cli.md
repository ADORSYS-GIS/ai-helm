# ADR-0007: Build `kc-token` as a single static Go binary + GH composite action

**Status:** Superseded by [ADR-0009](./0009-ai-in-ci-via-keycloak-token-exchange.md) (2026-05-24)
**Date:** 2026-05-24
**Deciders:** repo maintainers via `claude/magical-bohr-390242`

> **Why superseded:** Two assumptions in this ADR did not hold under
> scrutiny. (1) Humans don't need a CLI — the existing Lightbridge
> self-service portal (`self-service.ai.camer.digital`,
> `selfServiceMcpApi` Keycloak client) already issues API keys, so the
> device-flow rationale evaporated. (2) For CI, client-credentials with
> a static `client_secret` is the wrong shape — Keycloak OIDC token
> exchange (RFC 8693) lets us drop the long-lived secret entirely.
> ADR-0009 captures the replacement: a Python token-exchange step
> wrapped as a GitHub composite action. The content below is preserved
> as the historical record.

## Context

The Envoy AI Gateway exposes an OpenAI-compatible endpoint behind Keycloak
JWT authentication. Clients (human developers, CI runners, Python notebooks)
need to obtain a Keycloak access token and use it as `OPENAI_API_KEY` against
the gateway. Today there is no shared tooling — every caller hand-wires
their own token-fetching code.

We want a single ergonomic primitive that works in three contexts:
- **Shell**: `OPENAI_API_KEY=$(kc-token)` plus `OPENAI_BASE_URL=...`.
- **GitHub Actions**: a composite action that sets the env vars for
  subsequent steps using a service-account token.
- **Notebooks / scripts**: same shell command via `subprocess`, no need
  for a Python library.

The token has to support two grant types: device-authorization (RFC 8628)
for humans (no client secret, browser flow) and client-credentials for CI
(secret-based, non-interactive).

## Decision

Build `kc-token` as a single static **Go** binary distributed via GitHub
Releases (`goreleaser`) for `linux/amd64`, `linux/arm64`, `darwin/arm64`,
`darwin/amd64`.

- Default grant: **device-authorization** (RFC 8628). Prints a verification
  URL + user_code to stderr, polls the token endpoint, caches the refresh
  token.
- Opt-in: **client-credentials** via `--client-secret` / `KC_CLIENT_SECRET`
  / `--grant client_credentials`.
- Output: bare access token to **stdout**. All UX (prompts, QR, errors)
  goes to **stderr**. Enables `OPENAI_API_KEY=$(kc-token)` to compose
  cleanly with shell pipelines.
- Cache: `~/.cache/kc-token/<sha256(issuer+client_id+audience)>.json`,
  file mode 0600. Refresh token used transparently until both fail; cache
  invalidation on `--no-cache`.
- Flags: `--issuer` / `KC_ISSUER`, `--client-id` / `KC_CLIENT_ID`,
  `--audience`, `--scope` (default `openid`), `--grant`, `--client-secret`,
  `--no-cache`, `--quiet`.
- Ships a GitHub composite action at `kc-token-action/`: inputs map 1:1
  to flags, exports `OPENAI_API_KEY` and optionally `OPENAI_BASE_URL`.

Lives in this repo under `tools/kc-token/` to start; spun out to its own
repo if external consumers need to depend on it.

## Consequences

**Positive**
- One binary, no Python / Node runtime required at the caller. Works on
  bare CI runners, alpine containers, and developer laptops.
- Same UX in shell and in CI — flag set is identical to env-var set.
- Token caching means humans authenticate once per refresh-window
  (typically days), not per request.
- Composability: `kc-token` knows nothing about OpenAI specifically;
  the OpenAI URL is a separate env var. Same binary works against any
  Keycloak-protected API.

**Negative**
- Distribution overhead: GitHub Releases artifacts + checksums + a small
  installation snippet. Mitigated by GitHub's release ergonomics.
- A second language in the repo (today: Helm/YAML/shell; this adds Go).
  Justified by the cross-platform binary requirement.

**Neutral / follow-ups**
- If a Python-native interface becomes a real need (e.g. notebook authors
  prefer `from kc_token import get_token` over `subprocess`), wrap the
  binary with a thin Python shim later. Not building it now.
- A `kc-token-action` GitLab CI component is a possible follow-up if the
  GitLab path becomes load-bearing — but the existing `.gitlab-ci.yml`
  already auths via `OPENCODE_AUTH_JSON`, so the GH-Actions surface is
  the primary one.

## Alternatives considered

- **Python library + CLI + GH Action** — natural for the LLM tooling
  ecosystem (most LangChain / OpenAI SDK users are Python). Rejected
  because installing Python is overhead on minimal CI images, and the
  shell `subprocess` pattern works fine.
- **TypeScript library + CLI + GH Action** — same shape, npm. Better fit
  if LibreChat plugins / MCP servers needed to call it. Rejected for the
  same Python reason inverted.
- **Library + CLI + GH Action + GitLab component** — most reuse, most
  surface to maintain. Rejected; over-build for current needs.

## Related

- Task: #3 (implementation pending)
- Doc to be written: README under `tools/kc-token/` + a top-level
  `docs/openai-endpoint-authentication.md` that covers the end-to-end
  story (Keycloak client setup, audience claim, device-code UX,
  CI usage)
