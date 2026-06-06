# Linode → Hetzner cutover + domain rename (`ai-v2` → `ai`)

**Why is [ADR-0025](./adr/0025-linode-to-hetzner-cutover-domain-ai.md). This is the ordered runbook.**

Goal: make the **Hetzner** cluster (`aii-*`, today on `ai-v2.camer.digital`) the
production cluster on **`ai.camer.digital`**, migrating production data from the
**Linode** cluster (`ai-*`), then decommission Linode.

> ✅ **DNS already points at the Hetzner LB** and the rename is **merged + pushed**
> to the deploy branch (`f821a1b`). The outage rule (don't reconcile the rename
> before DNS resolves to Hetzner) is therefore satisfied. The remaining control is
> **manual sync**: root auto-sync/heal is disabled (Step 1), so nothing applies
> until you sync deliberately, in order.

## 0. State of the repo right now

- ✅ Domain renamed `ai-v2.camer.digital` → `ai.camer.digital` across
  `charts/**`, `environments/**`, `CLAUDE.md`, and operational docs (ADRs keep
  `ai-v2` as history). `domainBase: ai.camer.digital`. All charts render.
  **Merged + pushed** (`f821a1b`) — DNS is ready, so this is safe to sync.
- ✅ `scripts/migrate-librechat-mongo.sh` — the Mongo data move.
- ✅ DNS for the cutover hosts points at the Hetzner LB.
- ⚠️ One straggler: `charts/librechat-app/values.yaml` still has a cosmetic
  endpoint `iconURL` on `s3.ssegning.me` — it 404s once that S3 is gone; re-host
  the asset on Hetzner object storage (cosmetic, non-blocking).

## 1. Control — disable root auto-sync, sync manually in order

Instead of holding the push, take manual control so changes apply only when you
sync (and in a safe order — DB before the rename can churn certs, data before the
lightbridge DB recreate, etc.):
```bash
# disable automated sync+heal on the root so child-app changes don't auto-apply
kubectl --context admin@homeos -n argocd patch application ai-apps-v2 --type merge \
  -p '{"spec":{"syncPolicy":{"automated":null}}}'
# (and/or per child app, same patch on the aii-* apps you want to gate)
```
Re-enable `automated: {prune, selfHeal}` once cutover is verified (Step 5).

## 2. Migrate data (PRE-cutover — do it while DNS still points at Linode)

### LibreChat MongoDB
Run from this laptop (has both kubeconfigs). Auth-less mongo, tools run in-pod;
the dump is streamed to a local archive (= your backup) then restored.

```bash
# point OLD at the Linode kubeconfig (NEW defaults to the Hetzner one)
export OLD_KUBECONFIG=~/.kube/linode          # adjust to your Linode kubeconfig
# optional: export OLD_CONTEXT=...  OLD_NS=converse  OLD_POD=...

# 1) dry-run to confirm discovery + reachability (touches nothing)
./scripts/migrate-librechat-mongo.sh --dry-run

# 2) back up from Linode only (no writes to Hetzner), inspect the archive
./scripts/migrate-librechat-mongo.sh --dump-only

# 3) full migrate (dump + restore). Prompts before the destructive restore.
./scripts/migrate-librechat-mongo.sh
# then restart LibreChat on Hetzner so it reconnects:
KUBECONFIG=/Users/selast/dev/personal/hetzner-k8s/kubeconfig \
  kubectl -n converse rollout restart deploy/librechat-app
```
Re-runnable; keep the archive. To restore a saved archive later:
`./scripts/migrate-librechat-mongo.sh --restore-only ./mongo-migration-*/librechat-mongo.archive.gz`.

### Keycloak Postgres — out of script scope (decide before cutover)
The Mongo script does **not** touch Keycloak. Options:
- If the Hetzner Keycloak realm is already authoritative → nothing to do.
- Else migrate `keycloak-ha-cluster` (ns `keycloak`) out-of-band: a CNPG `import`
  bootstrap from the Linode PG, or a Keycloak **realm export/import** (preserves
  users only with the right flags). Track separately (ADR-0025 Consequences).

## 3. Pre-flight verification (before flipping DNS)

- Hetzner serving correctly on `ai-v2.*` today (gateway, LibreChat, Grafana).
- Migrated Mongo data present: `mongosh ... db.getSiblingDB('test').stats()` on
  the Hetzner pod shows the expected collections/counts.
- Hetzner LB external IP known (the data-plane LB; cf. `docs/2026-hetzner-cutover.md`).

## 4. Cutover — manual sync (DNS already done)

DNS already resolves to the Hetzner LB and the rename is pushed, so cutover =
**syncing deliberately**:
1. Confirm DNS: `dig +short api.ai.camer.digital` → Hetzner LB IP.
   (Hosts moved: `ai`, `api`, `api-main`, `api-mcp`, `mcp`, `grafana`, `analytics`,
   `platform`, `self-service`, `status`, `coder`, `*.coder-ai` — all `.camer.digital`.)
2. **Sync the root** (`ai-apps-v2`) so the regenerated child Application CRs carry
   the `ai.*` hosts, then **sync the child apps** (gateway/core-gateway first so its
   ACME cert reissues, then the rest). Trigger via the ArgoCD UI or
   `kubectl --context admin@homeos -n argocd patch application <app> --type merge -p '{"operation":{"sync":{}}}'`.
3. Watch cert issuance: the core-gateway ACME `Certificate` for
   `api.ai.camer.digital` should go `Ready` (HTTP-01 via the gatewayHTTPRoute now
   resolves). Grafana/coder certs likewise.

> ⚠️ When you sync the **lightbridge** app, see the lightbridge-split note — the
> CNPG `lightbridge-main-db` is moving from the flat app to the `lightbridge-db`
> child, which can prune+recreate it. Back up / migrate the main DB first.

## 5. Verify (post-cutover)

```bash
curl -sI https://api.ai.camer.digital/   # 200/401 from the gateway, valid TLS
# JWT path, models-info, LibreChat login (Keycloak redirect on ai.*), Grafana SSO
```
Re-enable any auto-sync suspended in Step 1.

## 6. Decommission Linode (`ai-*`)

Maintainer-only, on the Linode cluster. Never from this repo/ArgoCD root. Once
`ai.camer.digital` is fully served from Hetzner and data is verified, retire the
`ai-*` root + cluster.

## Rollback

Before Step 4 is trivial (DNS unchanged → Linode still serving; just don't push
the rename). After Step 4: revert DNS to the Linode IP and `git revert` the
domain commit (or re-suspend + roll Hetzner back to `ai-v2`). Keep the Mongo
archive; re-restoring onto Linode is possible with `--restore-only` pointed at the
Linode kubeconfig if data diverged.
