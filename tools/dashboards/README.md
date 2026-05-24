# Dashboard generators

Python source for every dashboard that ships into the cluster's Grafana via
the `grafana-operator` (`GrafanaDashboard` CRs). The generator emits JSON;
the JSON is committed in git and consumed by the
`charts/observability-dashboards` Helm chart (Layout B) or by an individual
app's chart `files/dashboards/` (Layout A).

**ADR:** [`docs/adr/0008-python-dashboard-generation.md`](../../docs/adr/0008-python-dashboard-generation.md)
**Architecture context:** [`docs/grafana-operator-and-dashboards.md`](../../docs/grafana-operator-and-dashboards.md)
**SDK:** [`grafana-foundation-sdk`](https://github.com/grafana/grafana-foundation-sdk) (Python flavor) — Grafana Labs' official, typed, multi-language dashboard SDK. Pinned to `1769699452!11.5.0` (the latest Grafana-11.x SDK on PyPI; emits `schemaVersion: 39`). PyPI uses `<epoch>!<grafana-version>` local-version identifiers — one Python release per Grafana minor.
**Toolchain:** `uv` + `ruff`, Python 3.12+

## TL;DR

```bash
uv sync                                     # one-time, installs deps from uv.lock
uv run dashboards build                     # regenerate every JSON
uv run dashboards check                     # CI guard: fail if committed JSON drifts from the .py source
uv run ruff format . && uv run ruff check . # format + lint
```

`make help` lists the same as Makefile targets.

## Layout

```
tools/dashboards/
  pyproject.toml          # uv-managed; SDK + ruff
  Makefile                # convenience wrappers
  README.md               # this file
  _common.py              # shared constants — no SDK imports
  main.py                 # orchestrator: walks modules, writes JSON
  <area>/
    __init__.py
    <name>.py             # exposes `build() -> dict` and `OUTPUT_PATH: str`
```

Current modules:
- `envoy_ai_gateway/per_user.py` → `charts/observability-dashboards/files/envoy-ai-gateway/per-user.json`

## Writing a new dashboard

1. Pick a Layout:
   - **Layout B (central)** for cross-app dashboards — write under
     `tools/dashboards/<area>/<name>.py`, target a path in
     `charts/observability-dashboards/files/<area>/<name>.json`.
   - **Layout A (chart-local)** for app-specific dashboards — write under
     `tools/dashboards/<chart>/<name>.py`, target the matching chart's
     `files/dashboards/<name>.json`.
2. The module must expose:
   ```python
   OUTPUT_PATH: str = "charts/.../files/<area>/<name>.json"
   def build() -> dict: ...
   ```
3. Import shared constants from `tools.dashboards._common` (datasource
   UIDs, Loki label keys, color palette, schema version). Don't redefine
   them locally.
4. Add the import string to `_DASHBOARD_MODULES` in `main.py`.
5. `uv run dashboards build` and commit the regenerated JSON.

## Why a Python generator at all

See ADR-0008. Short version: shared panel factories, single source for
datasource UIDs and label keys, compile-time schema contract (the SDK is
typed), and PR diffs that read as intent rather than serialization.

## The drift check

`uv run dashboards check` re-renders every dashboard to a tmpdir and
byte-compares against the committed file. The same command runs in CI on
every PR via [`.github/workflows/dashboards-drift.yml`](../../.github/workflows/dashboards-drift.yml).
Failure means someone hand-edited the JSON instead of the .py source — or
forgot to run `uv run dashboards build` after changing the .py source.

The error message tells you which file drifted and what to do. There is no
auto-fix in CI — the author commits the regenerated file.

## Generated-file banner

Every emitted JSON includes (or should include — see the per-dashboard
generator) a description string explaining that it's generated and pointing
at the source module. Hand-editors don't always read the doc; the banner
saves them.

## Updating the SDK

The SDK uses local-version identifiers like `<epoch>!<grafana-version>`.
`@latest` resolves to the highest semver, which is Grafana 10.1 — not what
you want. Instead, list available versions and pin explicitly:

```bash
# See what's available (versions are sorted by Grafana semver, not by date):
curl -s https://pypi.org/pypi/grafana-foundation-sdk/json | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print('\n'.join(sorted(d['releases'])))"

# Pin a specific Grafana-version SDK:
uv add 'grafana-foundation-sdk==1769699452!11.5.0'
uv run dashboards build                     # confirm output unchanged
git diff charts/                            # review any rendered drift
```

Pick a Grafana-version that matches (or is one minor behind) what the
cluster's grafana chart actually runs. Mismatch produces dashboards that
Grafana will migrate on every reconcile.

If the SDK rev changes the JSON shape (Grafana schema bumps, panel field
renames), the `check` command will catch the drift on the next CI run.

## Troubleshooting

- **`ModuleNotFoundError: tools.dashboards.<name>`** — every package
  directory (`tools/dashboards/`, `envoy_ai_gateway/`) needs an
  `__init__.py`. They exist; if you add a new subdirectory, add one too.
- **`OUTPUT_PATH` written to the wrong place** — paths are relative to the
  repo root, not to `tools/dashboards/`. The orchestrator does
  `repo_root / OUTPUT_PATH`.
- **`build` exits but the JSON is empty** — your `build()` returned `None`
  or a non-dict. Add a `return` statement.
