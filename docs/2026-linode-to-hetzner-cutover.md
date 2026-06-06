# Linode → Hetzner cutover + domain rename (`ai-v2` → `ai`)

**Why is [ADR-0025](./adr/0025-linode-to-hetzner-cutover-domain-ai.md). This is the ordered runbook.**

Goal: make the **Hetzner** cluster (`aii-*`, today on `ai-v2.camer.digital`) the
production cluster on **`ai.camer.digital`**, migrating production data from the
**Linode** cluster (`ai-*`), then decommission Linode.

> ⛔ **The single rule that prevents an outage:** the repo-wide domain rename is
> committed to the deploy branch, but **must not reconcile on Hetzner until DNS for
> `ai.camer.digital` points at the Hetzner LB.** If it syncs early, the in-chart
> ACME HTTP-01 cert for `api.ai.camer.digital` can't validate (DNS still → Linode),
> the gateway loses TLS for the new host, and the old `ai-v2.*` hosts are already
> gone → hard outage. Gate the sync on DNS (Step 4).

## 0. State of the repo right now

- ✅ Domain renamed `ai-v2.camer.digital` → `ai.camer.digital` across
  `charts/**`, `environments/**`, `CLAUDE.md`, and operational docs (ADRs keep
  `ai-v2` as history). `domainBase: ai.camer.digital`. All charts render.
- ✅ `scripts/migrate-librechat-mongo.sh` — the Mongo data move.
- ⏸️ **The domain-rename commit is intentionally held from `git push`** (or, if
  pushed, the Hetzner apps' auto-sync must be suspended) — pushing/syncing it is
  the cutover trigger (Step 4).

## 1. Freeze — stop Hetzner from auto-applying the rename

Pick one (so the rename doesn't reconcile before DNS):
- **Hold the push** (simplest): leave the domain commit unpushed until Step 4.
- **Or suspend auto-sync** on the Hetzner apps if the commit is already pushed:
  ```bash
  # disable automated sync on every aii-* app until cutover
  for a in $(kubectl --context admin@homeos -n argocd get applications \
              -o name | grep '/aii-'); do
    kubectl --context admin@homeos -n argocd patch "$a" --type merge \
      -p '{"spec":{"syncPolicy":{"automated":null}}}'
  done
  ```
  (Re-enable `automated: {prune,selfHeal}` after Step 5.)

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

## 4. Cutover — DNS, then sync

1. **Flip DNS** (Cloudflare) for every host below from the Linode IP to the
   **Hetzner LB IP**, low TTL first:
   `ai`, `api`, `api-main`, `api-mcp`, `mcp`, `grafana`, `analytics`, `platform`,
   `self-service`, `status`, `coder`, `*.coder-ai` — all `.camer.digital`.
2. **Wait for propagation** (`dig +short api.ai.camer.digital` → Hetzner LB).
3. **Trigger the rename**: `git push` the held domain commit (or re-enable the
   Hetzner apps' auto-sync from Step 1). ArgoCD reconciles the `ai.*` hosts.
4. Watch cert issuance: the core-gateway ACME `Certificate` for
   `api.ai.camer.digital` should go `Ready` (HTTP-01 via the gatewayHTTPRoute now
   resolves). Grafana/coder certs likewise.

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
