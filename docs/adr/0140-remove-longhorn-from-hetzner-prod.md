# ADR-0140: Remove Longhorn from hetzner-prod

**Status:** Accepted
**Date:** 2026-10-30
**Deciders:** @stephane-segning

## Context

ADR-0092 deployed Longhorn on `home-remote` (hetzner-prod), scoped by `nodeSelector`/tolerations
to the Hetzner Robot GPU nodes, and ADR-0093 put an oauth2-proxy in front of its UI. Both GPU
nodes have since left the cluster (`hetzner-k8s-gpu-2` on 2026-09-15, `hetzner-k8s-gpu-1`
after that — ADR-0138 started that withdrawal). With no node carrying `nvidia.com/gpu.present`,
`longhorn-manager`, `longhorn-csi-plugin` and `engine-image-*` have 0 desired pods, yet the
`longhorn-webhook-validator` / `longhorn-webhook-mutator` configurations (`failurePolicy: Fail`)
are still registered, and the validator covers `persistentvolumeclaims`. Every PVC update in the
cluster therefore fails with `no endpoints available for service "longhorn-admission-webhook"`,
which is what stopped the `webank` Application from syncing on 2026-10-30.

## Decision

Remove Longhorn from hetzner-prod, as a hard cutover (owner decision, 2026-10-30): delete the
`aii-longhorn` and `aii-longhorn-auth` entries from `charts/apps/values.yaml`, the
`longhorn-system` Pod Security elevation, and the `charts/longhorn-auth` and
`charts/longhorn-secrets` charts. `ai-helm-values` deletes the matching values and deps files,
and disables the one workload that used the `longhorn` StorageClass (`inference/qwen3-5-9b`).
The uninstall is operator-assisted, not a pure prune: see
`ai-helm-values` `docs/runbooks/longhorn-removal-hetzner-prod.md`.

## Consequences

**Positive**
- PVC updates cluster-wide stop depending on a webhook with no backend.
- One less privileged namespace and one less public UI (`longhorn.ai.camer.digital`).

**Negative**
- The GPU model fleet has no weights storage until a new ReadWriteMany StorageClass is chosen.
  `charts/inference-server/values.yaml` still defaults `pvc.storageClassName` to `longhorn`.
- The Longhorn volumes held re-fetchable model weights only; nothing is recovered.

**Neutral / follow-ups**
- `charts/keycloak-baseline` still declares the `longhorn-proxy` client and `longhorn_groups`
  scope; removing them deletes identity-provider state and is a separate change.
- Doc mentions of Longhorn in `charts/inference*`, `charts/llm-d` and `charts/model-serving-*`
  READMEs are historical and untouched.

## Related

- Supersedes: [0092](./0092-longhorn-for-hetzner-gpu-nodes.md), [0093](./0093-longhorn-ui-oauth2-proxy-role-restricted.md).
- Context: [0138](./0138-decommission-gpu-2-one-card-one-model.md).
