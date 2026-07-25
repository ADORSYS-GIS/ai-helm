# ADR-0092: Longhorn scoped to the Hetzner Robot GPU nodes only, via foreign-provider node isolation

**Status:** Accepted
**Date:** 2026-07-25
**Deciders:** @stephane-segning

## Context

Two Hetzner Robot dedicated servers (`hetzner-k8s-gpu-1`, `hetzner-k8s-gpu-2`) were
hand-joined to the `home-remote` (Hetzner) k3s cluster as GPU workers, outside
Terraform — see `hetzner-k8s` `docs/runbooks/add-gpu-node.md`. They carry a foreign
`providerID` (`baremetal://<host>`) and the label
`instance.hetzner.cloud/is-root-server=true` specifically so the hcloud Cloud
Controller Manager and the `hcloud-csi-node` DaemonSet leave them alone — Robot
boxes aren't in the hcloud Cloud API, and both components previously deleted the
node / crashlooped trying to treat it as one. The practical consequence: **these two
nodes have no CSI driver at all**, so nothing can provision a PVC on them.

LLM model-serving workloads on these nodes need persistent storage for multi-GB
model weight caches (pulled from S3, expensive to re-fetch on every pod restart).
Longhorn is the chosen distributed block storage system to fill that gap. Disk
headroom is not a constraint: each node has ~1.6 TB free on its existing RAID1 NVMe
root filesystem, host prerequisites (`open-iscsi`, `iscsid`, the `iscsi_tcp` kernel
module) are already installed and verified on both nodes.

⚠️ **A second, unrelated Longhorn instance already exists** on the `admin@homeos`
cluster, backing the `model-serving-qwen3-4b`/`model-serving-zimage-turbo` RWX PVCs
(`docs/patterns/self-hosted-model-serving.md`, `docs/models/qwen3-4b.md`). That one
is provisioned outside `ai-helm` entirely and is untouched by this decision — it is
easy to conflate the two because they share a product name; they are two separate
control planes, two separate clusters, two separate reasons to exist.

## Decision

Deploy Longhorn as a flat `charts/apps` Application (`aii-longhorn`, upstream chart
`https://charts.longhorn.io`, `valuesFromRepo: true` per ADR-0056), targeting
`home-remote` / namespace `longhorn-system` — **not** `homeCluster` (that field is
reserved for the one sanctioned ADR-0017/0022 exception, and does not apply here:
this Longhorn genuinely belongs on `home-remote`, same as every other GPU-node
workload).

Every Longhorn component — the static Manager DaemonSet, Driver Deployer, and UI
(via `global.nodeSelector`/`global.tolerations`), **and** Longhorn's own
dynamically-created system-managed pods, instance-manager and engine-image (via the
Longhorn Settings `defaultSettings.taintToleration` /
`defaultSettings.systemManagedComponentsNodeSelector`, a *separate* mechanism from
the Helm-level scheduling) — is pinned to nodes labeled `nvidia.com/gpu.present=true`
and tolerating the `nvidia.com/gpu=true:NoSchedule` taint. This means Longhorn can
**never** schedule onto a cp/worker node, so it cannot interfere with the working
`hcloud-csi` setup already serving those nodes' PVCs. `defaultSettings.createDefaultDiskLabeledNodes: true`
adds a second, independent restriction: only nodes explicitly labeled
`node.longhorn.io/create-default-disk=true` (applied to both GPU nodes out of band)
get a default disk, so a future accidental `nvidia.com/gpu.present` relabel
elsewhere can't silently hand Longhorn a data disk there too.

The chart's own `longhorn` StorageClass is created but **explicitly NOT set as
the cluster-default** (`persistence.defaultClass: false`) — `hcloud-csi`'s
`hcloud-volumes` StorageClass already holds that role
(`hetzner-k8s` `platform/helm-values/hcloud-csi-values.yaml`), and two default
StorageClasses is an ambiguous, invalid cluster state that a PVC omitting
`storageClassName` could resolve to either way. Workloads on the GPU nodes must
explicitly set `storageClassName: longhorn`; every other workload in the
cluster keeps landing on `hcloud-volumes` exactly as before — this decision
must have zero effect on any PVC that doesn't opt in by name.

`numberOfReplicas: 2` (one replica per GPU node — there are only two today;
Longhorn doesn't use Raft/quorum, so a 2-node topology is not degraded, just
less redundant than the chart's 3-replica default), V1 (filesystem-backed)
data engine only, `reclaimPolicy: Retain` (an accidental PVC delete shouldn't
destroy an expensive-to-refetch model cache — the tradeoff is orphaned PVs
need manual cleanup after a genuine decommission).

`longhorn-system` is added to `charts/apps` `global.namespacePodSecurity` as
`privileged` — Longhorn's V1 engine needs hostPath + privileged host access
(`/var/lib/longhorn`, `/dev`, iSCSI), which k3s/Hetzner's cluster-wide `baseline`
Pod Security Standard forbids without this elevation (same mechanism the
observability stack already uses for Alloy/node-exporter).

## Consequences

**Positive**
- Unblocks persistent storage on the GPU nodes without touching the hcloud-csi
  setup serving the rest of the cluster — zero blast radius on existing workloads.
- The node-scoping is enforced at two independent layers (Helm-level DaemonSet
  scheduling + Longhorn-internal Settings + default-disk labeling), so a partial
  misconfiguration in one layer doesn't silently spread Longhorn onto the wrong
  nodes.
- GitOps-managed (ArgoCD `automated: {prune, selfHeal}`), replacing what would
  otherwise be another hand-run `kubectl apply`/`helm install` on a pet node.

**Negative**
- Two replicas, not three: a disk failure on one GPU node degrades every volume to
  a single replica until repaired — there is no third node to fail over to today.
- `reclaimPolicy: Retain` means a mistaken PVC delete leaves an orphaned PV; cleanup
  is a manual `kubectl delete pv`, not automatic.
- The vSwitch link between these nodes and the rest of the cluster runs at MTU 1400
  (vs. 1450 on cloud nodes); Longhorn's own replica-sync traffic (distinct from pod
  traffic) crosses that link if a client pod and a replica ever land on different
  physical nodes — not expected to be a problem at today's model sizes, but worth
  watching if replica-rebuild times become a symptom.

**Neutral / follow-ups**
- Revisit `numberOfReplicas` (toward the chart default of 3) if a third GPU node
  joins.
- The two Longhorn instances (this one, and the pre-existing one on `admin@homeos`)
  are easy to conflate by name alone — `docs/architecture/07-data-secrets.md` now
  calls out the distinction explicitly.

## Alternatives considered

- **A plain `hostPath` or a standalone `local-path-provisioner` scoped to the GPU
  nodes** — simpler, no replication overhead. Rejected: no redundancy at all (a
  single node's disk failure loses the cache outright, forcing a full S3 re-fetch),
  and no GitOps-friendly StorageClass abstraction; Longhorn's replication cost is
  low at this scale (2 nodes, moderate model sizes) and buys real resilience.
- **Wire Hetzner Robot credentials into the hcloud CCM so these nodes become
  first-class hcloud-managed nodes, then use hcloud-csi normally** — would remove
  the need for a second storage system entirely. Rejected for now: bigger,
  riskier change to a component (`hcloud-csi`) that works correctly for every
  other node today; the CCM's Robot-API support is less battle-tested than its
  Cloud-API path. Left as an open question for a future ADR if the two-CSI-systems
  split becomes a real operational burden.
- **`numberOfReplicas: 3` today, accepting degraded volumes until a 3rd GPU node
  exists** — rejected in favor of `2`: a permanently-"degraded" healthy state is
  noisy (alerts/dashboards) for no actual redundancy benefit at the current
  2-node topology.

## Related

- Docs: `hetzner-k8s` `docs/runbooks/add-gpu-node.md` (the *how* of node
  enrollment); `docs/architecture/07-data-secrets.md` (disambiguates the two
  Longhorn instances); `docs/patterns/self-hosted-model-serving.md` (the other
  Longhorn's context).
- Builds on: [0017](./0017-home-remote-destination-invariant.md) (destination model), [0018](./0018-umbrella-apps-and-env-overlays.md) (umbrella pattern), [0022](./0022-self-hosted-gpu-model-federated-into-gateway.md) (the `homeCluster` exception this decision does *not* use), [0055](./0055-oci-charts-and-image-updater-writeback-to-values-repo.md)/[0056](./0056-workload-values-in-ai-helm-values.md) (continuous delivery + values-repo split).
- Charts/files touched: `charts/apps/values.yaml` (`aii-longhorn` app entry +
  `global.namespacePodSecurity`), `ai-helm-values` `environments/prod/values/longhorn.yaml`.
