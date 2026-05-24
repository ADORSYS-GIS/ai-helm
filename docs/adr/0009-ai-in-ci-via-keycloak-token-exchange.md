# ADR-0009: AI in CI via Keycloak OIDC token exchange (no long-lived secrets)

**Status:** Accepted
**Date:** 2026-05-24
**Deciders:** repo maintainers via `claude/magical-bohr-390242`
**Supersedes:** [ADR-0007](./0007-kc-token-go-cli.md)

## Context

CI workflows run OpenCode against the in-cluster Envoy AI Gateway
(`api.ai.camer.digital`, behind Keycloak JWT auth). Today each runner
needs a Keycloak access token; the path to get one is the open question.

Two shapes were on the table:

1. **Long-lived Keycloak `client_secret` as a CI variable** — the default
   pattern; rotation is manual, the credential lives in the vault for
   years, and a workflow compromise leaks a secret that's usable from
   anywhere on the internet for as long as the rotation cycle.
2. **Per-run federation via OIDC token exchange (RFC 8693)** — GitHub
   Actions issues a fresh OIDC ID token per job (audience-scoped),
   Keycloak validates against GitHub's JWKS and exchanges it for a
   Keycloak access token bound to the run's claims (`repository`,
   `actor`, `ref`, `workflow_ref`, `environment`).

ADR-0007 originally proposed a general-purpose `kc-token` Go CLI with
device-authorization (humans) and client-credentials (CI) grants. Two
assumptions there have changed:

- **Humans don't need a CLI.** The existing Lightbridge self-service
  (Keycloak client `selfServiceMcpApi` at
  `self-service.ai.camer.digital`) already issues API keys for human
  callers. That is the human path; no extra tool needed.
- **CI is the only remaining audience**, and the right shape for CI is
  token exchange, not client-credentials with a static secret.

## Decision

Build a small **Python step** that performs the GitHub Actions OIDC →
Keycloak token-exchange dance, wrapped as a **GitHub composite action**
for callers.

```yaml
- name: Acquire Keycloak token
  id: kc
  uses: ADORSYS-GIS/ai-helm/.github/actions/kc-exchange@<sha>
  with:
    issuer: https://auth.verif.fyi/realms/camer-digital
    audience: lightbridge-api-key
    client-id: adorsys-gis-github-ci
- name: Run OpenCode
  env:
    OPENAI_API_KEY: ${{ steps.kc.outputs.token }}
    OPENAI_BASE_URL: https://api.ai.camer.digital/v1
  run: opencode run --agent code-review
```

**Implementation:**
- Python 3.12 + `uv` + `ruff` (matches the toolchain from
  `tools/dashboards/`, locked in by the 2026 currency audit).
- Project at `tools/ci-keycloak-exchange/` with `pyproject.toml` and
  `uv.lock`.
- Reads `ACTIONS_ID_TOKEN_REQUEST_TOKEN` + `ACTIONS_ID_TOKEN_REQUEST_URL`
  from the runner env to fetch a GitHub-signed OIDC ID token whose `aud`
  matches the configured Keycloak audience.
- POSTs to Keycloak's token endpoint:
  - `grant_type=urn:ietf:params:oauth:grant-type:token-exchange`
  - `subject_token=<github-jwt>`
  - `subject_token_type=urn:ietf:params:oauth:token-type:jwt`
  - `audience=<keycloak-client-audience>`
  - `requested_token_type=urn:ietf:params:oauth:token-type:access_token`
- Writes the access token to `$GITHUB_OUTPUT` as `token` and optionally
  exports it as `OPENAI_API_KEY` to `$GITHUB_ENV` (action input toggle).
- Exits non-zero with a useful diagnostic on Keycloak rejection
  (claim-policy denials are common during the rollout).

**Pattern decisions baked in:**
- **One shared SA client** in Keycloak: `adorsys-gis-github-ci`.
  Claim-based policy in Keycloak discriminates by `repository` / `ref` /
  `job_workflow_ref`. Avoids per-repo client sprawl; one place to read
  the access matrix.
- **Fork PRs deny by default.** Keycloak token-exchange policy rejects
  when the GitHub JWT's `ref` is `refs/pull/N/merge` AND the source repo
  is outside the org's allowlist. Trusted-fork pattern is an explicit
  opt-in (per-policy).
- **GitLab support deferred.** The Python step is platform-agnostic in
  design (it reads a subject token from a chosen env var), but only the
  GitHub Actions composite-action wrapper ships today. GitLab CI
  component lands later.

## Consequences

**Positive**
- **Zero long-lived Keycloak secrets in CI.** The `client_secret` for
  `adorsys-gis-github-ci` becomes optional (kept only as a break-glass
  fallback if Keycloak token-exchange is down).
- **Per-run claims end up in observability.** Repository, ref, actor,
  and workflow-ref ride through Authorino response headers (ADR-0005's
  pipeline) into Loki labels. Per-user dashboards (ADR-0004) get a free
  per-CI-run breakdown — cost attribution by repo + workflow is
  emergent.
- **SA-skip-OPA (ADR-0003) keeps working unchanged.** The minted token
  still has `azp=adorsys-gis-github-ci`, which is in the allowlist.
- **Bounded scope.** One Python file, one HTTP exchange. No SDK,
  no Go toolchain in the repo.
- **Self-service path for humans is unchanged.** They get API keys via
  the existing Lightbridge self-service portal; no new tool to learn.

**Negative**
- Keycloak realm needs token-exchange enabled + a trust relationship for
  `token.actions.githubusercontent.com` and matching claim policies.
  Separate operator task (see Related).
- The shared SA pattern means an over-permissive Keycloak policy is one
  mistake away from "any CI run anywhere can mint a token for prod
  LLMs". Mitigated by fork-deny default + claim-based gating; the
  blast radius is recoverable by tightening policy.
- A Python runtime is fetched per CI run (uv handles this — fast
  in practice but a network dep).

**Neutral / follow-ups**
- Keycloak admin task: enable token-exchange, configure GitHub Actions
  IdP, write the initial claim policies (main vs PR vs fork). Tracked
  as a separate task.
- Implementation task: `tools/ci-keycloak-exchange/` + composite action
  at `.github/actions/kc-exchange/`. Tracked separately.
- GitLab parity: add `CI_JOB_JWT_V2` codepath + a GitLab CI component.
  Deferred.
- Once the shared-SA pattern stabilizes, revisit whether claim-based
  policy is fine-grained enough or whether per-repo clients pay back
  the audit cost.

## Alternatives considered

- **Long-lived `client_secret` in CI vars** — what we'd default to.
  Rejected: rotation pain, broad blast radius, undermines the rest of
  the security work.
- **Go CLI per ADR-0007** — would have served humans (device flow) and
  CI (client-credentials). Superseded: humans use self-service for API
  keys; CI is better served by token exchange (no secret at all) than
  by client-credentials (static secret). The CLI's surface no longer
  pays for itself.
- **Auth-code flow with browser redirect from CI** — non-interactive
  context. Doesn't work.
- **Vault-mediated exchange** (HashiCorp Vault as the OIDC consumer +
  Keycloak issuer) — adds a dependency we don't otherwise have. Same
  trust model as direct Keycloak exchange, more moving parts.
- **One SA client per repo** — finer audit, but `N` repos × per-repo
  realm config doesn't pay back. The claim-based policy on a shared
  client gives the same audit clarity from logs without the config
  sprawl.

## Related

- **Supersedes** [ADR-0007](./0007-kc-token-go-cli.md) — kc-token Go CLI
- [ADR-0003](./0003-skip-opa-for-service-accounts.md) — SA-skip-OPA via
  `azp` allowlist; the minted token still carries `azp=adorsys-gis-github-ci`
- [ADR-0005](./0005-per-user-attribution-via-authorino-headers.md) —
  the Authorino-headers→Loki pipeline that turns the per-run claims into
  dashboard labels
- New tasks (see queue): "Keycloak realm config for GitHub Actions token
  exchange" and "Python OIDC-exchange step + GH composite action"
- Doc to be written: `docs/ai-in-ci-keycloak-exchange.md` (the how —
  Keycloak admin recipe, action usage, troubleshooting)
