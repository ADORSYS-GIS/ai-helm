# ADR-0025: Cut over from Linode to Hetzner; rename the public domain `ai-v2.camer.digital` → `ai.camer.digital`

**Status:** Proposed
**Date:** 2026-06-06
**Deciders:** @stephane-segning

## Context

Two app generations run on the same ArgoCD (`admin@homeos`): the **`ai-*`**
generation on the **old Linode cluster** (current production, serving
`ai.camer.digital`) and the **`aii-*`** generation on the **new Hetzner cluster**
(`home-remote`), built and validated on the staging domain
**`ai-v2.camer.digital`**. The Hetzner build is now ready to take over. Cutover
means two things at once: **migrate the production data** Linode → Hetzner, and
**graduate Hetzner off the `-v2` staging domain** so it serves the real
`ai.camer.digital`.

The domain is **not** centralised — `domainBase` (`environments/prod/cluster.yaml`)
drives only the deps-overlay certs; the FQDN is hardcoded in ~180 places across
charts (gateway listeners, AuthConfig hosts, ingress TLS, Keycloak
redirect-URIs/audiences, LibreChat, opencode `.well-known`, the models-info
endpoint, observability). So the rename is a repo-wide string change, not a knob
flip.

## Decision

**Rename `ai-v2.camer.digital` → `ai.camer.digital` across all deployable config
(`charts/**`, `environments/**`) and operational docs, and cut Hetzner over to
production via an ordered, DNS-gated sequence.** ADRs keep `ai-v2` as historical
record (not retro-edited).

- **The domain change is staged on the deploy branch but its *push/sync is the
  cutover trigger*** — it must NOT reconcile before DNS for `ai.camer.digital`
  points at the Hetzner LB, or cert issuance (in-chart ACME HTTP-01) and gateway
  TLS break for the not-yet-resolving host while the old `ai-v2` hosts disappear.
- **Data migration is per-store.** LibreChat **MongoDB** moves via
  `scripts/migrate-librechat-mongo.sh` (auth-less mongodump→archive→mongorestore,
  run from a laptop with both kubeconfigs). **Keycloak/Coder Postgres are out of
  scope of that script** (see Consequences).
- **Ordered cutover** (full runbook: `docs/2026-linode-to-hetzner-cutover.md`):
  freeze Hetzner auto-sync → migrate data → flip DNS to Hetzner → push/sync the
  domain change → verify → decommission Linode (`ai-*`).

## Consequences

**Positive**
- One clean rename (no `-v2` cruft); Hetzner becomes the canonical production.
- The data path is a repeatable, backup-first script (the archive is kept).

**Negative / risks**
- **Syncing the domain change early = outage.** Mitigated by gating on DNS and
  withholding the sync (don't push the domain commit, or suspend the Hetzner
  apps' auto-sync) until cutover. This is the single most important constraint.
- **Keycloak data is not migrated by the script.** If the Hetzner Keycloak realm
  isn't already the source of truth, users/sessions/clients must be moved
  separately (CNPG `import` bootstrap, or a Keycloak realm export/import) — a
  decision deferred to the operator. Until then, treat Keycloak identity on
  Hetzner as authoritative or migrate it out-of-band before cutover.
- **Coder Postgres** is excluded (dev-only; the Hetzner `coder-cnpg` is currently
  unrecoverable and would need rebuilding first).
- Brief auth disruption at cutover: Keycloak redirect-URIs/audiences flip to
  `ai.*`, so any session mid-flight on `ai-v2.*` must re-auth.

**Neutral / follow-ups**
- DNS records to move to the Hetzner LB: `ai`, `api`, `api-main`, `api-mcp`,
  `mcp`, `coder` + `*.coder-ai`, `grafana`, `analytics`, `platform`,
  `self-service`, `status` (all `.camer.digital`).
- Old `ai-*` (Linode) apps are the maintainer's to decommission on that cluster —
  never touched from here.

## Alternatives considered

- **Centralise the domain into `domainBase` first, then flip one value** — the
  correct long-term shape (ADR-0018 `$values` Source C), but a large refactor to
  thread the knob through every chart's valuesObject; deferred. The literal rename
  is the smaller, reversible move for this cutover.
- **Blue/green on both domains simultaneously** — rejected: needs valid certs +
  DNS for both `ai-v2.*` and `ai.*` on Hetzner at once and dual Keycloak client
  config; more moving parts than a DNS-gated flip.
- **Migrate Keycloak Postgres in the same script** — descoped by the maintainer
  for this pass (Mongo only); Postgres migration is tracked as a follow-up.

## Related

- Docs: `docs/2026-linode-to-hetzner-cutover.md` (the ordered runbook + DNS list + rollback)
- Script: `scripts/migrate-librechat-mongo.sh`
- Builds on: ADR-0017 (destinations), ADR-0018 (`domainBase`/env overlays)
- Supersedes the staging-domain era recorded in ADR-0021 (which keeps `ai-v2` as history)
