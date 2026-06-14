# Python dashboard generation

How Grafana dashboards are authored in this repo, why the choice was made,
and the developer workflow.

**ADR:** [`docs/adr/0008-python-dashboard-generation.md`](./adr/0008-python-dashboard-generation.md) (the *why*)
**Project:** [`tools/dashboards/`](../tools/dashboards/) (the *code*)
**Operator wiring:** [`docs/grafana-operator-and-dashboards.md`](./grafana-operator-and-dashboards.md) (how the JSON gets into Grafana)

## At a glance

```
tools/dashboards/<area>/<name>.py             # source of truth — Python builder
            │
            │ uv run dashboards build
            ▼
charts/observability-dashboards/files/<area>/<name>.json   # committed JSON
            │
            │ rendered by helm template
            ▼
GrafanaDashboard CR (observability ns)        # reconciled by grafana-operator
            │
            ▼
Grafana UI                                    # visible to users
```

Two CI guards:
- `helm lint` / `helm template` (existing) — proves the chart renders.
- `dashboards check` (new) — proves the committed JSON matches what the
  generator would emit. Fails the PR otherwise.

## Why Python (and why this SDK)

Decided in ADR-0008. Short version:

- **Hand-written JSON** stops scaling around dashboard #3 — repetitive
  panel objects, no shared datasource UID / label key / color palette
  constants, brittle to schema bumps.
- **`grafanalib`** was the standard Python answer through 2024; the 2026
  currency audit found it lagging on panel types and lacking Grafana 12
  / v2-schema support.
- **`grafana-foundation-sdk` (Python)** — Grafana Labs' official,
  typed, multi-language builder. Tracks the live Grafana schema. Picked
  for parity with vendor direction. **Caveat:** as of 2026-05-24 the
  PyPI catalog has no Grafana-12-targeted release; we pin
  `1769699452!11.5.0` (the latest Grafana-11.x SDK) which emits
  `schemaVersion: 39`. Bumping to a 12.x SDK happens when both the SDK
  is published to PyPI AND the grafana chart upgrade (audit task #15)
  lands. See [`tools/dashboards/README.md`](../tools/dashboards/README.md)
  for the install pin + bump procedure.

## Project layout

```
tools/dashboards/
  pyproject.toml      — PEP 621, uv-managed, Python 3.12+, ruff for lint+format
  uv.lock             — committed; CI installs --frozen
  Makefile            — convenience wrappers around uv commands
  README.md           — developer workflow + troubleshooting
  _common.py          — shared constants: datasource UIDs, label keys,
                        SA client allowlist, color palette, time defaults,
                        SCHEMA_VERSION. Pure data — no SDK imports.
  main.py             — orchestrator; walks _DASHBOARD_MODULES and writes
                        each module's JSON to its OUTPUT_PATH.
  <area>/             — per-area packages
    __init__.py
    <name>.py         — exposes  OUTPUT_PATH: str
                                 def build() -> dict
```

## Layouts

ADR-0004 introduced two dashboard-shipping layouts; the generator supports
both, identical workflow.

| Layout | When | OUTPUT_PATH target |
|---|---|---|
| **B (central)** | Cross-app dashboards (per-user AI Gateway, total cost per user, GitOps overview) | `charts/observability-dashboards/files/<area>/<name>.json` |
| **A (chart-local)** | App-specific (LibreChat user activity, per-model gateway usage) | `charts/<chart>/files/dashboards/<name>.json` |

The grafana-operator picks both up — it reconciles every `GrafanaDashboard`
CR regardless of which chart shipped it. The choice is purely about
**ownership** (who pulls the bell when this dashboard breaks).

## Developer workflow

```bash
cd tools/dashboards
uv sync                                # one-time, reads uv.lock
# … edit envoy_ai_gateway/per_user.py …
uv run dashboards build                # regenerates the JSON
git diff charts/observability-dashboards/files/  # review the rendered change
uv run ruff format . && uv run ruff check .       # tidy
```

Commit BOTH the .py change and the regenerated JSON in the same commit.
The CI drift check enforces this.

## Adding a new dashboard

1. Pick a Layout (B for cross-app, A for chart-local).
2. Create `tools/dashboards/<area>/<name>.py`. Minimum shape:
   ```python
   from tools.dashboards._common import LOKI_UID, SCHEMA_VERSION
   # … SDK builder imports …

   OUTPUT_PATH: str = "charts/observability-dashboards/files/<area>/<name>.json"

   def build() -> dict:
       return (
           # … builder chain ending with .build() → dict …
       )
   ```
3. Add the import path to `_DASHBOARD_MODULES` in `tools/dashboards/main.py`.
4. `uv run dashboards build` and commit.
5. If Layout B, add a `dashboards:` entry in
   `charts/observability-dashboards/values.yaml` referencing the file.
   If Layout A, add a `GrafanaDashboard` CR template in your chart.
6. (Optional but encouraged) Add a sibling `README.md` describing each
   panel and the data path — see
   `charts/observability-dashboards/files/envoy-ai-gateway/README.md`
   as the template.

## The drift check (CI)

`.github/workflows/dashboards-drift.yml` runs on every PR touching
`tools/dashboards/**` or `**/files/**/*.json`. It re-renders every
dashboard to a tmpdir and byte-compares against the committed file.

Failure modes the check catches:
- Someone hand-edited the JSON in the chart (drift from generator).
- Someone changed the .py source but forgot `uv run dashboards build`.
- The SDK bump changed JSON output and the dashboards weren't regenerated.

The check does NOT auto-fix; the PR author commits the regenerated JSON.

## Generated-file marker

Each emitted JSON includes (or should include — set explicitly in
`build()`) a top-level `description` string explaining "GENERATED — see
`tools/dashboards/<module>.py`". Reviewers spot a stale JSON edit
immediately; the check catches the rest.

## SDK version pin + upgrades

The SDK pin lives in `tools/dashboards/pyproject.toml` under
`[project] dependencies`, mirrored in `uv.lock`. To bump:

```bash
cd tools/dashboards
uv add 'grafana-foundation-sdk@latest'   # or a specific version
uv run dashboards build                  # rebuild every dashboard
git diff charts/                         # review JSON drift
```

If the bump produced JSON drift, commit the regenerated files in the same
commit as the SDK pin bump. The drift check on the next PR will then
flag any subsequent unrelated drift cleanly.

## Coexistence with hand-written JSON

The grafana-operator doesn't care whether a `GrafanaDashboard` CR carries
generator-emitted JSON or hand-written JSON. If a one-off dashboard makes
more sense to hand-write (e.g. a 4-panel quick view that doesn't share
anything with other dashboards), do that — and mark it explicitly in the
JSON header (`description: HAND-WRITTEN — do not generator-port`) so the
drift check expects no .py source for it.

## Why a `uv.lock`

Reproducible installs. CI runs `uv sync --frozen`; without the lock, a
transitive SDK dep could shift between PR run and merge. Commit
`tools/dashboards/uv.lock` and treat it as source.

## Related

- ADR-0008 — the decision
- ADR-0004 — operator install + Layout A vs B
- ADR-0005 — the Loki labels the per-user dashboard consumes
- `docs/2026-currency-audit.md` — why this SDK, why uv + ruff
- `tools/dashboards/README.md` — developer-facing details + troubleshooting
- `charts/observability-dashboards/templates/dashboards.yaml` — how the JSON becomes a CR
