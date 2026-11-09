# ADR-0141: Cut the opencode well-known over to OpenCode v2 and the 0.18 plugins

**Status:** Accepted
**Date:** 2026-11-09
**Deciders:** @stephane-segning

## Context

The org-wide descriptor at `https://ai.camer.digital/opencode/.well-known/opencode`
(`charts/librechat-opencode-wellknown`, ADR-0014) pins the `@vymalo/*` plugins. The toolbeit's
[0.18.0](https://github.com/ADORSYS-GIS/lightbridge-opencode-toolbeit/blob/main/CHANGELOG.md)
is the OpenCode **v2** plugin-API cutover (toolbeit ADR-0019): it does not run on OpenCode v1,
and there is no dual export. Moving the pins off 0.17 therefore can't be a version bump. The
descriptor's whole `config` block has to move to the v2 shape: `plugins`, `providers`,
`settings`, `mcp.servers`, `permissions` rules, and `agents` with `system`/`request.body`. A v1
and a v2 client cannot share one document (toolbeit `docs/well-known.md`). Three hazards make
a hand-rewrite risky:

- **0.18 silently ignores v1-placed opt-ins.** OpenCode's own v1→v2 normaliser moves provider
  `options` to `settings` but leaves our `options.meta.*` block as `settings.meta.*`, which
  0.18 never reads. The `rateLimit` tiers and the `modelsInfo*` membership pruning would
  have switched off with no error.
- **v1 permission order was never the YAML order.** Helm's `toJson` (Go `encoding/json`)
  sorts map keys, so the rules live today ran in byte-sorted order. In v2, permissions are
  an ordered `findLast` list, so writing them in YAML order would have changed behaviour.
- **`opencode-skills-collection@4.0.14` is v1-only.** It exports a bare function, and v2
  needs the object entrypoint that 4.1.x ships.

## Decision

Hard-cut the descriptor to native OpenCode v2 (v2.2.6) in one change, with no v1 path.

- Pin `@vymalo/opencode-{lightbridge,models-info,ratelimit,browser}@0.18.0` and
  `opencode-skills-collection@4.1.40`.
- Rewrite `wellKnown.config` into native v2 keys. Flatten the plugin opt-ins onto
  `providers.camer-digital.settings`. Emit permission rules in the order that was **live**,
  not the YAML order. Write the MCP `timeout` as the v2 `{startup, catalog, execution}`
  object.
- Have `templates/configmap.yaml` inject the catalog-derived reasoning caps (ADR-0125) in the
  v2 model shape: `settings.reasoningEffort` plus `variants: [{id: thinking, settings}]`.

**Correctness is defined by OpenCode's own normaliser**
(`packages/core/src/config/normalize.ts` at v2.2.6), not by reading the YAML. Three checks:

1. The new render normalises with zero diagnostics.
2. It is a **fixed point**: `normalize(new) == new`. The normaliser ignores unknown
   properties, so a mis-keyed field would surface as a difference.
3. `normalize(new) == normalize(old)` plus exactly the intended changes (the pins and the
   `meta` flattening).

All three held at merge, rendered against the prod model catalog, with `old` identical to the
live endpoint's JSON.

## Consequences

**Positive**
- The plugins run on the API their maintainers now target; the 0.17 line is frozen.
- The descriptor is a deterministic fixed point of the host's own normaliser, so nothing in
  it is silently dropped. Future edits can be checked the same way.
- Tool scoping still holds on v2, re-verified in source rather than assumed. The root
  `permissions` are pushed first and each agent's rules after them
  (`config/plugin/agent.ts:63-104`). Evaluation is `findLast` (`permission.ts:94-98`). A tool
  is removed from injection when its last matching rule is a resource-`*` deny
  (`tool.ts:381-384`).

**Negative**
- **Every developer must be on OpenCode v2 at merge.** A v1 client fetches a document it
  cannot use, and 0.18 plugins don't load on v1. Announce the cutover with the merge.
- **The lightbridge gateway now fails closed.** When it can't resolve a bearer, 0.18 refuses
  the request locally (`lightbridge_gateway_no_bearer` at `warn`) instead of sending it
  unauthenticated.
- **Some telemetry signals stop.** Six OTel signals are no longer produced, including the
  lines-of-code metric and `opencode.file_edited`, so dashboards built on them go quiet
  without erroring.
- **The first model list can be un-enriched.** models-info now enriches via
  `model.transform` + `ctx.model.reload()`, so a session's first list may lack
  context/pricing until the catalog lands.
- `opencode-skills-collection@4.1.40` was hours old at pin time. It is pinned, not floated,
  so it can be rolled back deliberately.

**Neutral / follow-ups**
- Several YAML comments still describe the deny-baseline in v1 terms ("string form" vs
  nested map). The v2 equivalent is a rule with `resource: "*"`; the load-bearing comments
  were updated, and the rest are historical.
- `auth` (the `echo plugin-managed` stub + `env`) is unchanged; v2 keeps that shape.

## Alternatives considered

- **Bump the version strings only.** Rejected: 0.18 doesn't load on v1, and a v2 client
  would silently drop the `meta` opt-ins.
- **Serve v1 and v2 descriptors side by side at two URLs.** Rejected: it is a parallel
  compatibility path with a second document to keep in sync, which the maintainer's
  hard-cutover rule excludes. The 0.17 line is frozen anyway.
- **Ship v1 keys and let OpenCode's normaliser migrate them.** Rejected: the normaliser
  doesn't know our plugins' opt-in moves (`settings.meta`), and keeping v1 keys keeps the
  sorted-order permission trap.
- **Rewrite the YAML by hand.** Rejected as the *method*: the descriptor is ~2,000 lines
  with ~770 comment lines. A comment-preserving ruamel transform plus the normaliser
  fixed-point/equivalence check is verifiable where a hand edit is not.

## Related

- Upstream: toolbeit [`docs/migration-v2.md`](https://github.com/ADORSYS-GIS/lightbridge-opencode-toolbeit/blob/main/docs/migration-v2.md),
  toolbeit ADR-0019 / ADR-0020; OpenCode `v2.2.6` `packages/core/src/config/normalize.ts`,
  `packages/core/src/wellknown.ts`
- Docs: [`docs/integrations/opencode-well-known.md`](../integrations/opencode-well-known.md)
- Charts/files touched: `charts/librechat-opencode-wellknown/values.yaml`,
  `charts/librechat-opencode-wellknown/templates/configmap.yaml`
- Builds on: ADR-0014 (well-known split), ADR-0044/0048 (per-agent tool scoping),
  ADR-0074 (opt-in MCPs), ADR-0125 (catalog-derived reasoning caps), ADR-0135 (authz-idp
  login)
