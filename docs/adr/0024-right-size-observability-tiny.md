# ADR-0024: Right-size observability to a tiny footprint (cluster + Envoy AI usage, no alerting)

**Status:** Accepted
**Date:** 2026-06-06
**Deciders:** @stephane-segning

## Context

The LGTM stack (ADR-0020) was deployed close to its full distributed shape. The
actual requirement is narrow: **(1) observe the cluster** (metrics + logs +
traces) and **(2) observe Envoy AI Gateway usage** with per-user labels (ADR-0005:
Envoy access logs → Alloy → Loki). Nothing else — no HA, no big-cloud scale, no
alerting today.

Reality found in the live `home-remote` stack:
- **Loki** was already right (`SingleBinary`; the StatefulSet is the Loki binary,
  the two Deployments are just `gateway` + `canary`). No action needed.
- **Mimir** (`mimir-distributed` 5.8.0) ran the **full microservices topology**
  (~10 pods) and was **failing to sync**: every component set
  `podDisruptionBudget: { enabled: false }`, but that key doesn't exist in the
  chart's PDB block → `enabled: false` rendered into the PDB `.spec` and failed
  server-side apply (`.spec.enabled: field not declared in schema`). It also ran
  two dead chart-defaults (`rollout_operator`, `overrides_exporter`) — useless at
  `replicas: 1`, and `rollout_operator` was crashlooping on the Cilium
  default-deny-egress baseline. Its **Alertmanager** was enabled but idle (ruler
  disabled, Grafana `alerting.enabled: false`).
- **Grafana** (`grafana-external` operator CR) wasn't syncing — unrelated to
  scale: the `grafana-admin` ExternalSecret is in `SecretSyncedError` because
  `grafana_admin_user`/`grafana_admin_password` (+ the keycloak client secret)
  aren't populated in `ssegning-aws` `ai/camer/digital/prod/env`. An out-of-band
  fill, not a chart change.

## Decision

**Scope observability to the two stated needs and trim Mimir to its minimal
supported footprint; keep no in-cluster alerting.**

- **Mimir:** fix the PDB disable (`podDisruptionBudget: null`, not
  `enabled: false`) on every component — this clears the sync failure. Disable
  `rollout_operator` and `overrides_exporter`. **Remove Alertmanager entirely**
  (component + its `alertmanager_storage` S3 prefix + `structuredConfig.alertmanager`
  + the Grafana "Alertmanager" datasource). Keep one replica each of the essentials
  (ingester, distributor, querier, query-frontend, store-gateway, compactor, nginx)
  → **6 pods**. `mimir-distributed` 5.8.0 offers no true monolithic mode, so
  1-replica-per-component is the minimum here.
- **Loki:** leave as `SingleBinary` (gateway kept; canary is an optional drop).
- **Keep untouched:** the **Alloy** collector and its ADR-0005 Envoy
  access-log → `user_id`/`azp` attribution pipeline (that *is* the Envoy-AI-usage
  feature); Tempo (single replica, for trace↔log correlation); kube-state-metrics
  / node-exporter; the sync-wave ordering (MONITORING_FIX.md). Grafana's own
  `unified_alerting` → grafana-apprise-adapter path stays (Grafana-managed
  notifications, independent of Mimir).
- **No Mimir/cluster alerting** is provisioned. If recording/alerting rules are
  ever needed, re-introduce the ruler/alertmanager via a new ADR.

## Consequences

**Positive**
- Mimir syncs again (the PDB bug was the blocker) and drops from ~10 → 6 pods,
  shedding a crashlooping operator, a dead exporter, and an idle Alertmanager
  (one STS + one 10 Gi PVC). Footprint matches the requirement.
- Durable data is unchanged — all in S3 (`ssegning-k8s-state`); PVCs are WAL
  buffers only. Retention (90 d metrics/logs, 30 d traces) unchanged.

**Negative**
- **No in-cluster alerting/recording rules** — accepted (none existed). Adding
  them later means restoring the ruler/alertmanager (warrants an ADR).
- 1-replica components = no HA for the metrics path (acceptable for this tier; a
  Mimir restart drops a short ingest window, buffered by Alloy's WAL).

**Neutral / follow-ups**
- **Grafana is still down until the SM fill:** populate `grafana_admin_user`,
  `grafana_admin_password`, and the grafana-keycloak client secret in
  `ssegning-aws` `ai/camer/digital/prod/env`; the Grafana pod, the `grafana-external`
  operator CR, and the dashboards (incl. the Envoy-AI per-user dashboard) self-heal
  once the ExternalSecret resolves.
- Loki `canary` could be dropped for one fewer pod (cosmetic).

## Alternatives considered

- **Keep the full distributed LGTM** — rejected: over-provisioned for a homelab
  whose need is cluster-obs + one gateway's usage.
- **Replace Mimir with plain Prometheus** — rejected: a larger migration, and the
  S3-backed long-term retention already lives on Mimir; right-sizing Mimir is the
  smaller, reversible move.
- **Monolithic Mimir** — not offered by `mimir-distributed` 5.8.0 (a different
  image/chart); the 6.0 migration is breaking (nginx→gateway, rollout-operator
  CRDs) and out of scope.
- **Grant `rollout_operator` API-server egress** instead of disabling it —
  rejected: it does nothing useful at `replicas: 1` / zone-awareness off.

## Related

- Commits: `9f8610e` (PDB fix + drop rollout_operator/overrides_exporter), `3ec0d01` (remove Alertmanager)
- Builds on: ADR-0020 (observability App-of-Apps), ADR-0005 (Envoy per-user observability — the kept Alloy path)
- Charts/files: `charts/observability/values.yaml` (the `mimir` child); see `MONITORING_FIX.md` for the load-bearing sync-wave order
