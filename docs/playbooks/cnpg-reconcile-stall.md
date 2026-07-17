# CNPG `Managed` role reconcile stall

**Symptom:** A CNPG `Managed` role (e.g. `coder`) holds a stale password after the
backing `ExternalSecret` is refreshed. The Kubernetes Secret the `Managed` role
references is updated, but CNPG never re-reconciles the role in Postgres — the
old password stays active, and dependent workloads using the new credential are
locked out.

## Suspected root cause

The CNPG operator reconciles the `Managed` resource reactively — it watches the
`Managed` CR and the referenced Secret for changes. A reconcile stall can occur
when:

- The **operator's controller-manager restarted** (leader-election handoff,
  pod eviction, upgrade) and the watch was re-established *after* the
  Secret-change event, so the event was missed.
- The **informers' watch cache** has not yet observed the update
  (transient lag under load).
- The `Managed` resource itself lacks a periodic re-reconciliation field
  (unlike the `Cluster`'s `reconciliationIntervalSeconds`, `Managed` has no
  built-in `refreshAfter` — it only reacts to watch events).

## Investigation

1. **Check operator pod uptime:**
   ```bash
   kubectl -n cnpg-system get pods -l app.kubernetes.io/name=cnpg \
     -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.startTime}{"\n"}{end}'
   ```
   If the start time falls within the incident window, the operator likely
   restarted and missed the event.

2. **Check the referenced Secret timestamp:**
   ```bash
   kubectl -n converse get secret coder-db-role -o jsonpath='{.metadata.annotations}'
   ```
   Confirm the `reconciled` / last-updated timestamp is newer than the
   operator's last restart.

3. **Check CNPG logs for `Managed` reconciliation:**
   ```bash
   kubectl -n cnpg-system logs deploy/cnpg-controller-manager \
     --tail=200 | grep -i managed
   ```

## Remedy

Force the `Managed` resource to reconcile immediately:

```bash
kubectl annotate managedrole coder -n converse --overwrite \
  force-reconciliation="true"
```

CNPG reacts to any annotation change on the `Managed` CR. If the Secret is
already correct, this pushes the password to Postgres within seconds.

If the Secret itself is also stale, trigger an ESO refresh first:

```bash
kubectl annotate externalsecret coder-db-role -n converse --overwrite \
  force-sync="true"
```

## Prevention

- Consider adding a periodic `refreshAfter` to the CNPG `Managed`
  specification if the upstream CRD supports it (not in CNPG 1.x, tracked
  as a desired feature).
- The `Cluster` already has `reconciliationIntervalSeconds` — ensure it is
  set reasonably low (60–120s) so the operator periodically reconciles
  everything under it.
- If this pattern recurs, file a cross-repo investigation (CNPG operator in
  `home-os`, `Managed` role in this repo's `charts/lightbridge-db`).
