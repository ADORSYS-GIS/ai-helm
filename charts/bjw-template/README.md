# `bjw-template` + `bjw-common` — local fork of bjw-s app-template

Local fork of [`bjw-s-labs/app-template@4.6.2`](https://bjw-s-labs.github.io/helm-charts/docs/app-template/)
(application chart) and its accompanying
[`bjw-s-labs/common@4.6.2`](https://github.com/bjw-s-labs/helm-charts/tree/main/charts/library/common)
(library chart).

| | Upstream name | Forked name | Where it lives |
|---|---|---|---|
| Application wrapper | `app-template` | `bjw-template` | `charts/bjw-template/` |
| Function library | `common` | `bjw-common` | `charts/bjw-common/` |

## Why local

- **Control bump cadence.** Upstream cuts releases on its own schedule. The local fork lets this repo upgrade when it's ready and freeze when a release introduces a regression mid-rollout.
- **Patch in flight.** Add a label, fix a CRD schema, plug a security hole — all without waiting on upstream.
- **Reproducible without remote registry.** CI can render every chart from a clean checkout with no `helm repo add`.

## How consumers reference it

```yaml
# charts/<your-chart>/Chart.yaml
dependencies:
  - name: bjw-template
    version: '4.6.2'
    repository: file://../bjw-template
    alias: <your-app-name>       # values go under this key
```

Values, schema, and the loader (`controllers`, `service`, `ingress`,
`route`, `persistence`, `configMaps`, …) are **identical to upstream**.
Existing docs apply unchanged:
<https://bjw-s-labs.github.io/helm-charts/docs/app-template/>.

## One internal quirk: bjw-common is aliased back to `common` inside bjw-template

`charts/bjw-template/Chart.yaml` carries:

```yaml
dependencies:
  - name: bjw-common
    version: 4.6.2
    repository: file://../bjw-common
    alias: common      # ← required
```

The library's value-initializer
(`charts/bjw-common/templates/values/_init.tpl`) checks for
`.Values.common` by string — when that key isn't present, the merge is
skipped, `.Values` keeps Helm's `chartutil.Values` type, and a later
sprig `dig` call fails with:

```
interface conversion: interface {} is chartutil.Values, not map[string]interface {}
```

Aliasing the library back to `common` makes the lib's defaults land
under `.Values.common`, the init merge runs, `.Values` is replaced with
a plain map, and rendering proceeds.

Consumers don't see this detail — it's hidden inside bjw-template.

## Upgrading to a newer upstream

1. `helm pull --untar bjw-s/app-template --version <new>` (or download the tarball directly).
2. Overlay the upstream `templates/`, `values.yaml`, `values.schema.json` over `charts/bjw-template/`.
3. Overlay the upstream library's `templates/`, `values.yaml`, `values.schema.json` over `charts/bjw-common/`.
4. Bump `version:` in both `Chart.yaml` files.
5. Preserve the local headers and (critically) the `alias: common` line in `bjw-template/Chart.yaml`.
6. `helm dep build` every consumer chart that depends on `bjw-template`.
7. `helm template + helm lint` each consumer to verify.

## Consumers in this repo

Every chart that uses bjw-template:

- `charts/ai-models-info` (`alias: models-info`)
- `charts/keycloak-baseline` (`alias: config-sync`)
- `charts/keycloak-backup` (no alias — values keyed under `bjw-template:`)
- `charts/librechat-admin-panel` (`alias: admin-panel`)
- `charts/librechat-app` (`alias: librechat`, conditional)
- `charts/librechat-opencode-wellknown` (`alias: opencode-wellknown`)
- `charts/lmcache` (`alias: lmcache`)
- `charts/mcpo` (`alias: mcpo`)
- `charts/model-deployment` (`alias: serving`)
- `charts/models-proxy` (`alias: proxy`, conditional)
- `charts/mongodb-backup` (`alias: mongodb-backup`)
- `charts/pgdump-backup` (no alias — values keyed under `bjw-template:`)

See ADR-0016 for the decision context.
