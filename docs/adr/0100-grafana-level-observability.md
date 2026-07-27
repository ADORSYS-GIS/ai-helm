# ADR-0100: Grafana-level observability — self-health and per-user anomaly alerts

**Status:** Accepted
**Date:** 2026-07-27
**Deciders:** @stephane-segning
**Builds on:** [ADR-0059](./0059-grafana-unified-alerting-to-discord.md) (the Discord alerting pipeline these rules plug into), [ADR-0058](./0058-precompute-gateway-usage-metrics-to-mimir.md) (the gen_ai metrics the user-activity rules use), [ADR-0023](./0023-grafana-stateless-no-pvc.md) (stateless Grafana)

## Context

ADR-0059 shipped the first-pass alerting set: AI gateway traffic/errors/cost,
stack health, and cluster basics (pod crashloops, node readiness, node memory).
That covers **cluster-level** observability — the things that break the
infrastructure the AI gateway runs on.

It does NOT cover **Grafana-level** observability:

1. **Grafana itself can be down** — and when it is, the dashboards that would
   show the outage can't render, and the alerting rules that would fire can't
   evaluate. The whole observability stack goes dark silently.
2. **A single user can be doing something unusual** — a runaway script, a
   stolen token, a credential-stuffing attack. The aggregate cost guardrails
   in ADR-0059 smooth these away: one user doing 100x their baseline is
   invisible in a sum that averages across all users.
3. **Disk fills slowly and silently** — the existing cluster-health rules
   cover CPU and memory, but disk pressure is a separate failure mode (logs,
   container images, ephemeral volumes) that doesn't show up in memory
   metrics until pods start failing to write.

## Decision

Extend the existing  section in 
with three additions, all routed through the existing Discord contact point
(ADR-0059). No new contact points, no new secrets, no new infrastructure.

### 1.  rule (added to existing  group)

Watches  on the root
filesystem. Fires at 85% full for 15m — deliberately before kubelet's own
 condition (default 85% per ), giving
a lead time to clean up before pods get evicted.

### 2. New  rule group (folderRef: )

Three rules watching Grafana's own  endpoint (scraped into Mimir as
):

| Rule | Fires when |
|---|---|
|  |  for 5m — the UI is down or the pod is crash-looping |
|  |  > 0.1/s for 10m — a datasource is broken and dashboards backed by it are silently empty |
|  |  for 10m — likely a misconfigured rule spamming the contact point |

### 3. New  rule group (folderRef: )

Three rules for per-user anomaly detection on the AI gateway:

| Rule | Fires when |
|---|---|
|  | A single user's 1m request rate is >10x their 1h baseline for 5m — possible runaway script or compromised token |
|  | Same shape on tokens rather than request count — catches a user burning through context (huge prompts, long conversations) even if their request count looks normal |
|  | AI Gateway 401/403 rate > 1/s for 10m (Loki) — possible credential stuffing or token-guessing attack |

The 10x threshold on the burst rules is deliberately generous to avoid paging
on normal weekday-vs-weekend swings; tune live once firing.

## Why these specific rules (not others)

- **Grafana auditing / usage_insights** would give us richer signals (who
  logged in, who changed what, per-user dashboard usage), but the actual
  Grafana instance is configured in the  repo (ADR-0056,
  ) — out of scope for this repo. The 
  metrics used here are exposed by Grafana's built-in  endpoint
  regardless of whether  is enabled.
- **Keycloak login failure metrics** would be the ideal signal for the
  auth-failure rule, but Keycloak is not in the observability stack's scrape
  targets (it lives in ). The AI gateway's 401/403
  responses are the next-best signal — they're the gateway rejecting bad or
  expired tokens, which is what a credential-stuffing attack produces.
- **Per-IP auth failure burst** would be more precise than aggregate 401/403
  rate, but the Loki logs don't currently carry a stable client-IP label
  in the parsed JSON. Aggregate rate is the best signal available without
  adding a new log parser.

## Consequences

- Grafana outages are now visible — the  rule fires before
  anyone notices the UI is missing.
- Per-user abuse (runaway scripts, stolen tokens, credential stuffing) is
  now detectable at the gateway level, not just in aggregate spend.
- Disk pressure gets a lead-time warning before kubelet starts evicting.
- All rules route through the existing Discord contact point — no new
  secrets, no new infrastructure.
- Thresholds are first-pass (per ADR-0059's pattern) and will need a live
  tuning pass once alerts are firing against real traffic, especially the
  10x burst thresholds and the 0.1/s datasource error rate.
