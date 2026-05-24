# ADR-0002: Replace Arize Phoenix with Grafana Tempo for LLM tracing

**Status:** Accepted
**Date:** 2026-05-24
**Deciders:** @stephane-segning

## Context

LLM call traces from the Envoy AI Gateway were being shipped to two backends
in parallel: Arize Phoenix (in `converse-monitoring` ns, with its own
ingress at `analytics.ai.camer.digital`, its own Postgres, its own Keycloak
client + scope + 3 groups) AND Grafana Tempo (in `observability` ns,
already running with persistent S3 storage as part of the LGTM stack).

Phoenix added an Application, two PVCs, a namespace, an OIDC client, a DNS
record, and a small constellation of audit-flagged anti-patterns:

- The core-gateway chart's PDB template wrote PDBs into the `converse-monitoring`
  namespace from a chart deployed to `converse-gateway` — cross-namespace
  writes that need cluster-scope permission and are a known source of sync
  conflicts.
- The OTLP exporter endpoint was hardcoded to a Phoenix-specific Service name.
- The auth secret name was misspelled (`pheonix-otel-key`).

Tempo + Grafana already provide everything Phoenix did at this scale (trace
storage, search, service-graph view), and we are migrating dashboards to
the operator path (ADR-0004) where adding LLM-specific tracing views is
cheap.

## Decision

Remove Phoenix end-to-end. Rename the core-gateway traces collector from
`-phoenix` to `-traces`, drop the Phoenix exporter from its config, retire
the Keycloak `phoenix` client/scope/groups, and delete the Phoenix
ArgoCD Application. LLM tracing flows: gateway → `-traces` OTel collector
→ Alloy → Tempo. Visualization lives in Grafana on top of the Tempo
datasource.

## Consequences

**Positive**
- One trace backend to operate, monitor, and scale. Same operational
  surface as logs (Loki) and metrics (Mimir) — uniform.
- Three audit findings resolved by removal (cross-namespace PDBs,
  hardcoded endpoint, typo'd secret).
- Less infra cost: no second Postgres, no second ingress, no second
  Keycloak client to rotate.

**Negative**
- Phoenix-specific UX (eval scoring, prompt comparison views) is gone.
  Mitigated: those features were not yet in active use, and Grafana with
  Tempo + TraceQL covers the day-to-day observability path.
- Out-of-band cleanup required: orphaned Secret, PVCs, namespace, DNS
  record. Enumerated in `docs/migrations/phoenix-to-tempo.md`.

**Neutral / follow-ups**
- If LLM-eval becomes a need, the right tool is likely the OTel
  semconv `gen_ai.*` attributes already on the spans (logged in the access
  log JSON), queried via TraceQL — not a separate platform.

## Alternatives considered

- **Keep both, ship traces to both** — Phoenix's exporter is already
  configured. Rejected: doubles the operational surface for no net benefit,
  and the audit anti-patterns get worse over time, not better.
- **Keep Phoenix in dev only, gated by env flag** — would require chart
  conditionals and a dev/prod values split. Rejected: nobody on the team
  uses Phoenix actively; preserving a fallback we don't operate is dead
  weight.
- **Migrate to a different LLM-eval tool (Langfuse, LangSmith, etc.)** —
  trades one external dependency for another. Rejected: no specific
  feature gap that justifies adding a new platform today. Revisit if
  evaluation becomes a real workflow.

## Related

- Commit: `a134215`
- Doc: `docs/migrations/phoenix-to-tempo.md` (the how + the out-of-band
  cleanup checklist)
- Charts touched: `charts/core-gateway/templates/{otel,gateway-config,pdb}.yaml`,
  `charts/apps/values.yaml`, `charts/keycloak-baseline/values.yaml`
