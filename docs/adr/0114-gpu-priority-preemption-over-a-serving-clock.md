# ADR-0114: Free GPUs for MLOps by priority preemption, not by a serving clock

**Status:** Proposed
**Date:** 2026-08-02
**Deciders:** @stephane-segning

## Context

The fleet has **two** GPUs (`hetzner-k8s-gpu-1/2`, one RTX 4000 SFF Ada each) and
[ADR-0094](0094-generic-model-serving-orchestrator.md) allocates them a whole card
at a time — `gpu.count: 1`, no MIG, no time-slicing, one model per card. Two
catalog entries are enabled (`qwen3-vl-4b-thinking`, `z-image-turbo`), so **both
cards are claimed 24/7** and the fleet is full by design: a third consumer sits
`Pending` with `Insufficient nvidia.com/gpu`, which ADR-0094 explicitly calls "the
queue working, not a bug".

The third consumer has now arrived. `charts/webank-training` renders
WorkflowTemplates whose dataset-build **and** training steps each request
`nvidia.com/gpu: 1`, and the chart `fail`s the render if that limit is below 1
([workflowtemplate.yaml:14](../../charts/webank-training/templates/workflowtemplate.yaml)).
The maintainer's ask is to make serving **disappear on a clock** — 21:00–06:00 on
weekdays, 18:00–10:00 on weekends — so MLOps owns the cards the rest of the time.

Three facts constrain the answer.

**1. The contention is real but currently unreachable.** Verified live on
2026-08-02, no GPU workflow pod can land on either card *regardless* of what
serving is doing. The deployed WorkflowTemplates select `nodeSelector: {role: gpu}`
and tolerate `role=gpu:NoSchedule`; the actual nodes carry neither:

| | Workflow templates expect | Live GPU nodes have |
|---|---|---|
| Label | `role=gpu` | `nvidia.com/gpu.present=true`, `node-role.kubernetes.io/gpu=""` |
| Taint | `role=gpu:NoSchedule` | `nvidia.com/gpu=true:NoSchedule` |

**No node in the cluster carries a `role` label at all** (checked across all 9).
This is not a values typo that `ai-helm-values` could fix on its own: the chart's
own guards *enforce* the wrong contract — it hard-fails unless
`training.gpu.nodeSelector.role == "gpu"` and a matching `role=gpu` toleration is
present, so `ai-helm-values` `environments/prod/values/webank-training.yaml` is
merely obeying it. Both selector and toleration are wrong in the same direction,
so the failure is total, silent, and predates this discussion. **Whatever
mechanism frees a card, it buys nothing until this is fixed.**

**2. Imperative scaling loses to ArgoCD.** The inference children sync with
`prune: true, selfHeal: true` ([values.yaml](../../charts/inference/values.yaml)),
so a `kubectl scale` is reverted — the same mechanism that already reverts
`rollout restart` on the nginx charts. Any replica-driven scheduler needs
`ignoreDifferences` on `/spec/replicas` to coexist, and KEDA — the purpose-built
tool for a cron `ScaledObject` — is not installed on this cluster; installing it
is a `home-os` change, since shared cluster infrastructure lives there.

**3. The requested clock is a large, unconditional giveaway.** Serving up 06:00–21:00
on weekdays and 10:00–18:00 at weekends is **91 of 168 hours (54%)** — the cards go
dark for 77 hours a week whether or not a workflow is submitted, and a run that
starts late or overruns its window gets nothing anyway.

## Decision

**Arbitrate the GPUs by pod priority and let the scheduler preempt, instead of
putting serving on a clock.** MLOps work takes a card *when it is actually
submitted*; serving occupies both cards the rest of the time.

Concretely:

- Two cluster-scoped `PriorityClass` objects, both `globalDefault: false`
  (only one class cluster-wide may be the global default, and neither of these
  should be it):

  | Name | Value | Applies to |
  |---|---|---|
  | `inference-serving` | `-10` | every `charts/inference-server` pod |
  | `mlops-training` | `1000` | every GPU-requesting `charts/webank-training` step |

  Serving is deliberately **negative**: it is the designated victim and must never
  be able to preempt anything itself, including an unprioritized pod at the default
  0. Training uses the default `preemptionPolicy: PreemptLowerPriority`.

- **Plumbing is a passthrough, not new machinery.** `bjw-common` already exposes
  `defaultPodOptions.priorityClassName` ([values.yaml:73](../../charts/bjw-common/values.yaml)),
  so `charts/inference` gains a `defaults.priorityClassName` knob emitted from the
  existing `defaultPodOptions` block in its `_helpers.tpl` — the same place
  `runtimeClassName`/`nodeSelector`/`tolerations` are already set. `charts/webank-training`
  gains `training.gpu.priorityClassName`, rendered onto the GPU templates.

- **Fix the placement contract in the same change**, as a prerequisite: the
  chart's guards and the values must select `nvidia.com/gpu.present=true` and
  tolerate `nvidia.com/gpu=true:NoSchedule`, matching the nodes as they are
  actually bootstrapped (`hetzner-k8s` `docs/runbooks/add-gpu-node.md`) and
  matching what `charts/inference` already tolerates. Priority is meaningless
  between pods that cannot target the same node.

- The `PriorityClass` objects ship from **this repo** as a minimal chart with a
  flat `charts/apps` entry targeting `home-remote` at sync wave `-1`, not from
  `home-os`. They are cluster-scoped, which argues for `home-os`, but both
  consumers are ai-helm workloads and the values encode an ai-helm policy
  ("serving yields to training"), not cluster plumbing. The orchestrator itself
  cannot carry them — `charts/inference` is a control object rendering an
  ApplicationSet into `argocd` in-cluster (ADR-0017), and a per-leaf copy would
  put every child in contention over the same cluster-scoped object.

**The clock is not built.** If preemption proves insufficient in practice, a KEDA
cron `ScaledObject` composes *on top* of this — a schedule guarantees a floor of
free GPU, priority handles everything outside it — and that is tracked as a
follow-up rather than pre-built.

## Consequences

**Positive**

- **Demand-driven.** A card is surrendered when a workflow is submitted and
  returned when it finishes, so the 77 hours/week the clock would have given away
  unconditionally stay served unless someone is actually training.
- **No window to miss.** Starting late, running long, or working a Tuesday
  afternoon all behave identically. Nothing to keep in sync with DST, holidays, or
  a change of habit — a cron schedule would need an explicit timezone and would
  drift an hour twice a year if hardcoded to UTC.
- **No new operator and no ArgoCD fight.** Preemption is stock kube-scheduler
  behaviour; replica counts never change, so `selfHeal` has nothing to revert and
  no `ignoreDifferences` exception is needed.
- Serving pods return automatically — the Deployment's replacement pod is simply
  `Pending` at priority `-10` until a card frees up. No second mechanism has to
  remember to turn serving back on.
- Fixes a live, total MLOps GPU outage that the scheduling question would
  otherwise have masked.

**Negative**

- **Serving goes down without notice and without a window.** Under the clock,
  users would at least have had a predictable outage; under preemption the model
  disappears whenever a run starts. In-flight requests are killed at eviction —
  `terminationGracePeriodSeconds` bounds the wait, it does not drain.
- **The model stays advertised while it is gone.** Federation is a separate
  `charts/ai-models` entry, so scaling to zero by any means leaves the model listed
  in `/v1/models` and returning 503s — the "advertised but not served" failure mode
  [ADR-0101](0101-load-gate-before-federation-no-exceptions.md) and
  [ADR-0109](0109-ready-means-served-warmup-startup-probe.md) were written about,
  accepted knowingly here rather than solved.
- **Return is not free.** vLLM reloads ~8.6 GiB of weights from the Longhorn PVC,
  and the image tier pays ADR-0109's real-generation startup probe (~32 s cold)
  before it is `Ready` again. Frequent preemption converts directly into cold-start
  latency for users.
- **Thrash.** A workflow made of several short GPU steps can evict and readmit
  serving repeatedly; there is no minimum-uptime mechanism, and the mitigation is
  the soft one of keeping GPU steps coarse.
- **Both models can go at once.** Two parallel GPU steps take both cards, so the
  text *and* image tiers can be down simultaneously — the clock would have done
  the same, but on a schedule.
- Preemption honours PodDisruptionBudgets only on a best-effort basis, so a PDB
  cannot be used to bound the above.
- Serving at a negative priority is also ranked first for kubelet node-pressure
  eviction. That is consistent with the intent, but it is a second eviction path
  that did not exist before.

**Neutral / follow-ups**

- The placement-contract fix must land first or with this change; it is worth
  confirming live afterwards that a GPU workflow pod actually schedules, since
  nothing has ever demonstrated that on this cluster.
- **No alerting exists for "serving was preempted."** Today the symptom is a
  silent 503. A follow-up should alert on an inference Deployment sitting at zero
  available replicas beyond a threshold, so an unexpectedly long training run is
  visible rather than inferred from user reports.
- If the cards turn out to be contended most of the day, the honest answer may be
  the null option below (permanently free one card) rather than either arbitration
  scheme; the numbers to make that call do not exist yet.
- The 3-consumer-2-card arithmetic is unchanged by this ADR. Preemption decides
  *who yields*, not *how much capacity exists*.

## Alternatives considered

- **A cron schedule, exactly as requested (KEDA cron `ScaledObject`)** — the
  purpose-built tool: `minReplicaCount: 0` plus two triggers (`0 6 * * 1-5` →
  `0 21 * * 1-5`, `0 10 * * 6,0` → `0 18 * * 6,0`). Rejected as the *primary*
  mechanism, not as a bad idea: it surrenders 46% of serving availability whether
  or not the GPUs get used, gives nothing to a run that starts outside its window,
  requires installing KEDA via a `home-os` change, and needs an `ignoreDifferences`
  exception on `/spec/replicas` for every inference child so `selfHeal` stops
  fighting it. Kept as a composable follow-up if preemption alone proves too
  unpredictable.
- **A CronJob patching replicas, plus `ignoreDifferences`** — hand-rolled KEDA
  with an RBAC'd ServiceAccount in `inference`. Rejected: the same
  `ignoreDifferences` requirement and roughly the same wiring as KEDA, but
  imperative, unobservable, and with a bespoke failure mode (a missed CronJob run
  leaves serving off indefinitely). Only preferable if installing KEDA were
  blocked outright.
- **A scheduled bot commit flipping `enabled:` in the catalog** — the only option
  that keeps git the source of truth for GPU occupancy. Rejected: the catalog lives
  in **this** repo, not `ai-helm-values`, so the bot would push to `main` four
  times a day — and under [ADR-0055](0055-oci-charts-and-image-updater-writeback-to-values-repo.md)
  a merge to `main` is a live deploy, each one triggering an OCI chart publish and
  release-please churn. A scheduler that manufactures releases is the wrong shape.
- **Permanently disable one model (the null option)** — one line, zero machinery,
  a card free 24/7. Not rejected on merit and explicitly still the right answer if
  MLOps needs only one card and serving can live with one tier: it is simply a
  capacity decision, not a scheduling one, and it gives up a served tier around the
  clock to cover intermittent use.
- **GPU time-slicing or MPS** — rejected on hardware. The card is 20475 MiB, vLLM
  already holds a deliberate 60% ceiling, and training needs real VRAM rather than
  interleaved access; sharing would OOM both tenants.
- **ArgoCD sync windows** — rejected on a misreading worth recording: they gate
  *syncing*, not scheduling. A sync window neither stops a running pod nor frees a
  GPU.

## Related

- Charts/files touched: `charts/inference/values.yaml`,
  `charts/inference/templates/_helpers.tpl`, `charts/webank-training/`,
  `charts/apps/values.yaml`, plus the new PriorityClass chart
- Values repo: `ai-helm-values` `environments/prod/values/webank-training.yaml`
  (GPU placement block)
- Builds on: [ADR-0094](0094-generic-model-serving-orchestrator.md) (one card per
  model, queue-by-request), [ADR-0017](0017-home-remote-destination-invariant.md)
  (why the orchestrator cannot ship cluster-scoped objects),
  [ADR-0098](0098-deployment-recreate-instead-of-statefulset.md) (`Recreate`, so an
  evicted pod terminates before its replacement starts)
- Tension with: [ADR-0101](0101-load-gate-before-federation-no-exceptions.md) and
  [ADR-0109](0109-ready-means-served-warmup-startup-probe.md) — this ADR knowingly
  reintroduces windows where a federated model is not served
- Inference-side context: the team's `inference-ops` repo
