# Longhorn orphaned-volume cleanup runbook

When a model is decommissioned or replaced, its PVC is deleted but the Longhorn
StorageClass `reclaimPolicy: Retain` keeps the underlying PV (and the Longhorn
volume) alive — see [ADR-0092](../adr/0092-longhorn-for-hetzner-gpu-nodes.md).
This runbook is the manual cleanup step that ADR anticipates.

> ⚠️ **Destructive and irreversible.** Deleting a volume destroys its data
> permanently (weights would have to be re-downloaded from S3/HuggingFace). Do
> **not** run this without explicit per-volume owner sign-off recorded on the
> tracking ticket first.

## When to use this

- After decommissioning or replacing an inference model, to reclaim its weights
  volume.
- During a storage audit, to identify and clean up accumulated orphans.

## 1. Enumerate Longhorn volumes and cross-reference against PVCs

List all Longhorn volumes with their state, robustness, size, and origin:

```bash
kubectl -n longhorn-system get volumes.longhorn.io \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.state}{"\t"}{.status.robustness}{"\t"}{.spec.size}{"\t"}{.status.kubernetesStatus.pvStatus}{"\t"}{.status.kubernetesStatus.namespace}{"\t"}{.status.kubernetesStatus.pvcName}{"\t"}{.status.kubernetesStatus.lastPVCRefAt}{"\n"}{end}'
```

List all PVCs to cross-reference:

```bash
kubectl get pvc -A
```

## 2. Identify orphans

A volume is a **candidate orphan** when **all** of these hold:

- `state: detached`
- `robustness: unknown`
- `kubernetesStatus.pvStatus: Released`
- `kubernetesStatus.pvcName` is **not** present in the live PVC list (no owning
  PVC)

**Exclude** any volume that is:
- `attached` / `healthy` (in use), or
- `Bound` to a live PVC (even if currently detached — e.g. a build-output claim),
  or
- a known cold-standby backup for a model.

## 3. Get explicit owner sign-off

For each candidate, record on the tracking ticket:
- the volume name, size, and original PVC/model (from `kubernetesStatus.pvcName`
  and `workloadsStatus[0].workloadName`)
- confirmation it is genuinely orphaned (not a cold-standby backup)
- explicit owner approval to delete

**Do not proceed to step 4 until every volume has explicit sign-off.**

## 4. Delete the retained PV, then the Longhorn volume

Order matters: delete the PV first (releases the retained PV object), then the
Longhorn volume (frees the storage/replicas).

```bash
# 4a. Delete the retained PV(s)
kubectl delete pv <pv-name-1> <pv-name-2> ...

# 4b. Delete the Longhorn volume(s) — frees the storage
kubectl -n longhorn-system delete volumes.longhorn.io <volume-name-1> <volume-name-2> ...
```

## 5. Verify and record freed capacity

Confirm the volumes are gone:

```bash
kubectl -n longhorn-system get volumes.longhorn.io
kubectl get pv
```

Record on the tracking ticket the total freed capacity and the verification
result.

## Example

Deleting the 8 orphaned inference volumes from ticket #998 (355 Gi):

```bash
kubectl delete pv \
  pvc-2df23414-33bd-47d0-8ed5-ade533aea589 \
  pvc-444a5f76-57a4-4976-bec6-057ae49ab293 \
  pvc-6d99623b-2987-4930-84d8-8781802af3a6 \
  pvc-6eadc222-968c-46e2-959e-814575dbf3bd \
  pvc-734357fc-934b-4492-8a87-aebd398a28c0 \
  pvc-789169ae-dc0f-46a2-8233-7adba9536b63 \
  pvc-ebebcd56-fcb4-4f43-93ff-a5f07c38f9d1 \
  pvc-f1de4aae-9992-4011-aa53-adc418dac8d2

kubectl -n longhorn-system delete volumes.longhorn.io \
  pvc-2df23414-33bd-47d0-8ed5-ade533aea589 \
  pvc-444a5f76-57a4-4976-bec6-057ae49ab293 \
  pvc-6d99623b-2987-4930-84d8-8781802af3a6 \
  pvc-6eadc222-968c-46e2-959e-814575dbf3bd \
  pvc-734357fc-934b-4492-8a87-aebd398a28c0 \
  pvc-789169ae-dc0f-46a2-8233-7adba9536b63 \
  pvc-ebebcd56-fcb4-4f43-93ff-a5f07c38f9d1 \
  pvc-f1de4aae-9992-4011-aa53-adc418dac8d2
```
