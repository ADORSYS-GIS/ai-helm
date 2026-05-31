# ADR-0016: Fork bjw-s app-template + common library locally as bjw-template / bjw-common

**Status:** Accepted
**Date:** 2026-05-31
**Deciders:** @stephane-segning

## Context

Twelve charts in this repo depend on
[`bjw-s-labs/app-template`](https://bjw-s-labs.github.io/helm-charts/docs/app-template/)
(the "common-powered chart template" — the de-facto convention in this
repo for any workload-shaped chart that doesn't need bespoke
templates). The upstream chart is pulled from
`https://bjw-s-labs.github.io/helm-charts` at `helm dep build` time.

Two pressures on that setup:

1. **Cadence.** Upstream cuts releases on its own schedule. A regression
   landed mid-cycle would block every consumer here until upstream
   shipped a fix; conversely, we'd inherit a breaking minor (e.g.
   schema additions) at the next `helm dep update` whether or not we
   wanted it.
2. **Patchability.** If a label or annotation contract changed in this
   repo (say, observability tooling expecting a specific selector), we
   could not patch the library without forking out-of-band and pointing
   at a private repo.

The two charts touched by this PR's recent migration
([`librechat-opencode-wellknown`](../../charts/librechat-opencode-wellknown/),
[`ai-models-info`](../../charts/ai-models-info/)) and the ten
pre-existing bjw-s consumers all use the same upstream version family
(4.x). Forking now consolidates the surface before there are more
charts to chase.

## Decision

Fork both upstream charts into the repo:

- `charts/bjw-template/` — copy of `app-template@4.6.2` (the wrapper).
- `charts/bjw-common/` — copy of `common@4.6.2` (the library).

Every consumer's `Chart.yaml` now references the local forks:

```yaml
dependencies:
  - name: bjw-template
    version: '4.6.2'
    repository: file://../bjw-template
    alias: <…>
```

No upstream `https://bjw-s-labs.github.io/helm-charts` reference remains
in any chart's dependencies.

The forks' template code is **byte-identical** to upstream — only
`Chart.yaml` (name + maintainers + sources) differs, and `bjw-template`
gains one extra line:

```yaml
dependencies:
  - name: bjw-common
    repository: file://../bjw-common
    version: 4.6.2
    alias: common      # ← see "alias" note below
```

### The alias-back-to-`common` quirk

The bjw-s library's value initializer
(`charts/bjw-common/templates/values/_init.tpl`) checks for
`.Values.common` by string literal:

```go
{{- if .Values.common -}}
  {{- $defaultValues := deepCopy .Values.common -}}
  ...
  {{- $_ := set . "Values" (deepCopy $mergedValues) -}}
{{- end -}}
```

Without that merge, `.Values` keeps Helm's `chartutil.Values` type, and
a later `dig "defaultPodOptionsStrategy" "overwrite" $rootContext.Values`
call in `_getOption.tpl` fails:

```
interface conversion: interface {} is chartutil.Values, not map[string]interface {}
```

If we register the library under its new name `bjw-common`, its
defaults flow under `.Values.bjw-common`, the if-check fails, the
merge is skipped, and every consumer breaks the moment a pod has
`annotations: {}` (i.e. always).

Aliasing the dep back to `common` inside `bjw-template/Chart.yaml`
restores the value path the library expects. Consumers don't see this —
it's hidden inside the wrapper chart.

This is the **only** functional difference between the fork and
upstream. A future upstream that drops the string check (or accepts
either key) would let us drop the alias; until then the alias is
load-bearing and documented in `bjw-template/Chart.yaml`.

### Version normalization

Three consumers were on older pins:

| Chart | Pre-fork pin | Post-fork pin |
|---|---|---|
| `lmcache` | `4.3.0` | `4.6.2` |
| `mcpo` | `4.1.2` | `4.6.2` |
| `models-proxy` | `'*'` | `4.6.2` |

All three render-verified post-bump. bjw-s minors are
backward-compatible for the values shapes these charts use. Normalizing
at the fork eliminates the "which version does this consumer get" head
math going forward.

## Consequences

**Positive**
- One source of truth for the bjw-s library in this repo. Every consumer pulls from the same `file://../bjw-template`.
- No network needed at `helm dep build` time for the bjw-s chunk. CI render + lint work from a clean checkout.
- Upgrade-on-our-schedule. Bumping is a deliberate PR that updates both `charts/bjw-template/` and `charts/bjw-common/` together, regenerates locks, and runs the consumer matrix.
- In-flight patching is now a normal commit, not a private fork.

**Negative**
- One more thing to upgrade. Upstream improvements (new resource kinds, security fixes, schema additions) only land here when we deliberately overlay them. Mitigation: the upgrade procedure is documented in `charts/bjw-template/README.md`; if upstream cuts a security release, it's a 30-minute mechanical overlay + render-test.
- The `alias: common` inside `bjw-template/Chart.yaml` is load-bearing and non-obvious. Mitigation: an inline comment plus this ADR plus the wrapper README explain why.
- Two extra chart directories to maintain in this repo. Small in absolute terms (the library is ~50 template files but they don't change).

**Neutral / follow-ups**
- An upstream change that drops the `.Values.common` literal check
  would let us remove the alias. Watch upstream changelogs.
- If a security advisory targets a specific bjw-s common version, the
  overlay procedure in `charts/bjw-template/README.md` is the
  fast path.

## Alternatives considered

- **Pin to the upstream chart and never bump.** Doesn't address the
  patchability gap, and leaves CI dependent on the bjw-s registry being
  reachable. Rejected.
- **Fork to a separate private Helm repo and consume via OCI.** Cleaner
  separation but reintroduces the "needs network at build time"
  constraint, and adds infra (registry, auth, CI publish step) for
  little gain. Rejected.
- **Fork only the library (`bjw-common`), keep `app-template` from
  upstream.** Would require yanking the alias dep upstream uses — the
  upstream `app-template` references `common`, not `bjw-common`, so
  we'd have to patch every release. Cleaner to fork both. Rejected.
- **Don't rename — keep upstream chart names (`app-template`,
  `common`).** Would clash with our existing `charts/common/` (Bitnami
  library library) sharing the same name in the file-tree. Renaming
  disambiguates. Accepted.

## Related

- ADR-0012 — orchestrator-plus-leaves pattern used by `ai-models`. Most
  leaves there don't use bjw-template (they emit CRDs), but the
  pattern's ApplicationSet wiring is unaffected.
- ADR-0014 — librechart split. The four leaves there (`librechat-app`,
  `librechat-admin-panel`, `librechat-search`, `librechat-opencode-wellknown`)
  use bjw-template via the fork as of this ADR.
- ADR-0015 — `ai-models-info` chart. Migrated to bjw-template in this PR.
- `charts/bjw-template/README.md` — the how-to (upgrade procedure,
  consumer list, alias-back-to-`common` rationale).
- `charts/bjw-common/README.md` — pointer to the wrapper.

## Files

- `charts/bjw-template/` — new (forked app-template)
- `charts/bjw-common/` — new (forked common library)
- `charts/{ai-models-info,keycloak-baseline,keycloak-backup,librechat-admin-panel,librechat-app,librechat-opencode-wellknown,lmcache,mcpo,model-deployment,models-proxy,mongodb-backup,pgdump-backup}/Chart.yaml` — re-pointed dep
- `charts/{keycloak-backup,pgdump-backup}/values.yaml` — renamed `app-template:` key → `bjw-template:` (no-alias consumers key values by chart name)
