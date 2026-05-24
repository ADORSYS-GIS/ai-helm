# ADR-0008: Generate Grafana dashboards from Python

**Status:** Proposed
**Date:** 2026-05-24
**Deciders:** repo maintainers via `claude/magical-bohr-390242`

## Context

ADR-0004 chose grafana-operator with `GrafanaDashboard` CRs and committed
dashboard JSON. The first dashboard
(`charts/observability-dashboards/files/envoy-ai-gateway/per-user.json`)
is ~350 lines of hand-written JSON. Three dashboards in, the pattern shows
its costs:

- Panel objects are repetitive (same legend, tooltip, fieldConfig defaults
  block, with one or two interesting fields). Hand-written JSON encourages
  copy-paste drift.
- Datasource UIDs, label keys, and color palettes are duplicated across
  every dashboard.
- Reviewing a JSON diff for a panel layout change is unpleasant.
- Grafana's JSON schema evolves with releases; a typo today might render
  fine and break silently after a Grafana bump. There is no compile-time
  contract.

A code-generated approach gives us: shared helpers, typed panel
constructors, single source for constants (datasource UIDs, label keys),
and a `git diff`-able Python source that is small even when the rendered
JSON is large.

## Decision

Adopt a **Python generator** under `tools/dashboards/` that emits
dashboard JSON to `charts/observability-dashboards/files/<area>/<name>.json`
(Layout B) and `charts/<chart>/files/dashboards/<name>.json` (Layout A).

**Tool:** `grafana-foundation-sdk-python` — Grafana Labs' official,
multi-language, typed builder SDK. The 2026 currency audit
(`docs/2026-currency-audit.md`) confirmed it has overtaken `grafanalib`
as the dominant Python-for-Grafana approach and is the only path with
first-party Grafana 12 (CUE-based v2 dashboard schema) support.

Conventions:
- Project at `tools/dashboards/` with `pyproject.toml` (PEP 621), managed
  by **`uv`** (confirmed 2026-standard by the audit). `ruff` for
  lint+format (replaces black + isort + flake8 in one tool).
- Modules grouped by area: `envoy_ai_gateway/per_user.py`, etc.
- Shared `_common.py` exposes datasource UIDs (`MIMIR_UID="mimir"` etc.),
  label keys, color palette, panel-default factories.
- `main.py` walks every module and writes JSON to the target paths.
- Generated files carry a header banner: `// GENERATED — do not edit; see
  tools/dashboards/<module>.py`.
- CI: `uv run check` (or `make verify`) re-generates and
  `git diff --exit-code`s the dashboard files. Drift fails the build.
- First migration: convert the existing `per-user.json` to its Python
  representation as the proof of round-trip.

## Consequences

**Positive**
- Shared panel/variable constructors eliminate copy-paste drift.
- A typed library (if chosen) catches schema bumps at generator-build time
  rather than at Grafana-render time.
- PR diffs are Python source, not JSON. Reviewers see intent, not
  serialization.
- New panel = one function call.
- The generator is a natural place to enforce conventions
  (every panel must specify a datasource by UID, never by name; every
  variable must declare `multi` + `includeAll`).

**Negative**
- Adds a Python toolchain to the repo (today: Helm/YAML/shell; ADR-0007
  adds Go; this adds Python). Two new languages in two ADRs.
- One more thing to keep in sync — the generator dependency, the schema
  version it targets, and the Grafana version actually running. The CI
  drift check is the main mitigation.
- Authors who prefer to draft a dashboard in the Grafana UI and export
  JSON now have a one-extra-step path: convert the exported JSON into
  Python source. Helper script can ease this; document it.

**Neutral / follow-ups**
- The generator's target schema version tracks the cluster's grafana.
  Today: `schemaVersion: 42` (Grafana 12). Bumping grafana to 12.x (per
  the audit punch list item #8) and re-emitting all dashboards happen
  together.
- Eventual successor ADR if a different generator approach proves
  better (e.g. jsonnet via `grafonnet`, or a TypeScript-based emitter
  for parity with frontend tooling). Not on the horizon.

## Alternatives considered

- **Hand-written JSON (status quo)** — works, but the costs scale linearly
  with dashboard count and panel count. Rejected as default; remains the
  fallback for trivial one-off dashboards.
- **`grafanalib`** — longstanding, simple Python DSL. Rejected: audit
  found it lags on recent panel types and lacks Grafana 12 / v2-schema
  support. Was the 2024 obvious pick; no longer the 2026 obvious pick.
- **Jsonnet via `grafonnet`** — dominant in CNCF-adjacent observability
  projects (Mimir, Loki, Tempo all use it). Strong type inference via
  jsonnet objects. Rejected because Python is already the team's data/ops
  language; adding jsonnet adds a build dependency with no composability
  benefit over the official Python SDK.
- **TypeScript generators** — viable; parity with potential future
  frontend code. Rejected today because nothing else in this repo is
  TypeScript.
- **Just YAML templates expanded via Helm** — would tie dashboard
  authoring to Helm template syntax (`{{ }}` collisions with Grafana's
  variable substitution, painful debug). Rejected.

## Related

- Task: #11 (implementation pending; blocked by audit #9)
- ADR-0004 (operator + CRs), ADR-0005 (per-user labels — the data the
  first dashboard renders)
- Doc to be written: `docs/python-dashboard-generation.md`
