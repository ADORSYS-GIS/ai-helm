# `bjw-common` — local fork of bjw-s common library

Helm library chart. Local fork of
[`bjw-s-labs/common@4.6.2`](https://github.com/bjw-s-labs/helm-charts/tree/main/charts/library/common).

Renamed from `common` → `bjw-common` to disambiguate from the
Bitnami `common` library that already lives at `charts/common/`.

## Don't depend on this directly

Application charts should depend on `bjw-template` (the wrapper at
`charts/bjw-template/`), NOT on `bjw-common` directly. `bjw-template`
already pulls in this library with the correct alias and value layout.

See [`charts/bjw-template/README.md`](../bjw-template/README.md) for
the full story and the upgrade procedure.
