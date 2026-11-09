# ADR-0142: A temporary OpenCode v1 bridge descriptor beside the v2 one

**Status:** Proposed
**Date:** 2026-11-09
**Deciders:** @stephane-segning

## Context

[ADR-0141](./0141-opencode-v2-cutover-of-the-wellknown.md) hard-cut the org-wide descriptor
at `https://ai.camer.digital/opencode/.well-known/opencode` to native OpenCode v2. Its
consequence "every developer must be on OpenCode v2 at merge" left anyone still on v1 with a
descriptor their client can't use and plugins that won't load on it. The 0.18+ plugins don't
run on v1, and a v1 and a v2 client can't share one document. In practice not everyone could
upgrade on the same day.

ADR-0141 rejected "serve v1 and v2 descriptors side by side at two URLs" **as a design**,
because it creates a second document to keep in sync. That reasoning still holds, and this ADR
does not reverse it. What's needed is a short, deliberately unmaintained bridge so the people
who haven't upgraded aren't stuck while they do.

## Decision

Serve the **frozen pre-cutover v1 descriptor** from a second URL for a fixed window. The v2
descriptor stays the only maintained one, and ADR-0141 stands.

- **URL:** `https://ai.camer.digital/opencode-v1/.well-known/opencode`. A v1 client runs
  `opencode auth login https://ai.camer.digital/opencode-v1`. OpenCode appends
  `/.well-known/opencode` to whatever it's given, so the bridge needs its own path prefix, not
  a new filename. A different origin is a different integration on the client, so the two
  don't collide.
- **Content:** `charts/librechat-opencode-wellknown/files/wellknown-v1.yaml`, the `wellKnown`
  block exactly as it was at `63c6bf57^` (the commit before the cutover), with comments kept.
  Plugins stay on the frozen v1 line: `@vymalo/*@0.17.0` and `opencode-skills-collection@4.0.14`.
  The file is read with `.Files.Get`, so it can't be overridden from `ai-helm-values`. That is
  deliberate: nobody should end up maintaining it.
- **Rendering:** the same chart, pod and content ConfigMap. The ConfigMap gets a second key,
  `opencode-v1`, built with the template as it stood before ADR-0141 (catalog-derived reasoning
  caps in the v1 shape: per-model `options`, `variants` as a map). nginx gains one exact-match
  `location`, and the Ingress gains one `Exact` path on the same host and cert.
- **Frozen, not synced.** Agent, permission, MCP and plugin changes go to v2 only. The bridge
  only picks up new reasoning caps, because those come from the model catalog.
- **Sunset: 2026-12-09.** On or before that date, delete the file, the `opencode-v1` key, the
  nginx `location` and the Ingress path in one PR, and mark this ADR `Superseded`/retired. Every
  bridge-only line is commented "TEMPORARY … (ADR-0142)" so the removal is a grep.

**Verification at merge.** The `opencode-v1` key renders byte-identical (after `jq -S`) to the
chart at `63c6bf57^` rendered against the prod model catalog. The v2 `opencode` key is
unchanged from `main`, and `main`'s render equals the live endpoint.

## Consequences

**Positive**
- Developers on v1 keep working and can upgrade on their own schedule within the window.
- No change to the v2 descriptor or to ADR-0141's contract. The bridge lives entirely in
  clearly labelled, removable lines.

**Negative**
- v1 users don't get fixes. They run the 0.17.0 plugins and the agent/permission/MCP set as it
  was on 2026-11-09. If the gateway or `authz-idp` later changes something 0.17 depends on, the
  bridge breaks and we won't fix it. The answer is to upgrade.
- A second URL in circulation, which people may bookmark. The sunset has to be announced, and
  after the cutoff the path returns 404.
- The 0.17 lightbridge plugin sends a request unauthenticated when it can't resolve a bearer
  (0.18 fails closed, per ADR-0141). This is unchanged from the behaviour before the cutover.

**Neutral**
- `pathType: Exact` routing on the same host, cert and Service. No DNS, TLS or `ai-helm-values`
  change.

## Alternatives considered

- **Reverse ADR-0141 and maintain both.** Rejected: that is the parallel-maintenance cost
  ADR-0141 refused, and nothing here needs it.
- **No bridge, tell people to upgrade.** Still the default, and what happens at sunset. It was
  rejected only for this window.
- **Make the bridge overridable from `ai-helm-values`.** Rejected: it would invite edits to a
  document that's supposed to be frozen.

## Related

- Builds on: [ADR-0141](./0141-opencode-v2-cutover-of-the-wellknown.md) (does NOT supersede it),
  [ADR-0014](./0014-split-librechart-and-opencode-wellknown.md)
- Docs: [`docs/integrations/opencode-well-known.md`](../integrations/opencode-well-known.md)
- Files: `charts/librechat-opencode-wellknown/files/wellknown-v1.yaml`,
  `charts/librechat-opencode-wellknown/templates/configmap.yaml`,
  `charts/librechat-opencode-wellknown/values.yaml` (Ingress path)
