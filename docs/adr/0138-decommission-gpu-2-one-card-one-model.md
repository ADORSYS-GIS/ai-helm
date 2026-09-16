# ADR-0138: Decommission `hetzner-k8s-gpu-2` — one card, one model, image generation withdrawn

**Status:** Accepted
**Date:** 2026-09-15
**Deciders:** @stephane-segning

> ⚠️ **Erratum — 2026-09-15, after the live rollout.** The body below claims
> twice (Decision §2, and the first "Negative" consequence) that removing an
> agent from `agentSeed` does **not** delete the DB agent, leaving
> `image-creator` as an orphaned Mongo document. **That is wrong.** The seed
> script has an explicit prune phase — `charts/librechat-app/files/seed-agents.js:132-147`
> deletes every agent authored by the platform user that is no longer in the
> fleet, deliberately scoped to `author == platform user` so it never touches
> agents real users created. The fleet is declarative, not an append-only
> upsert. The live run confirmed it: `[agent-seed] pruned image-creator
> (agent_Oo2rOizVp7loelF7HMz9i)` → `done: 5 agents`. So there is **no orphaned
> document and no follow-up cleanup** — the outcome was cleaner than this ADR
> predicted, not dirtier. ⚠️ The practical consequence runs the other way:
> because a rename creates a new agent and prunes the old, the `agent_id` in a
> withdrawn `modelSpec` comment is only valid while the agent's *name* is
> unchanged. The body is left intact per the immutability rule; this note is
> the correction.

## Context

The GPU fleet has run on two Hetzner Robot dedicated nodes since
[ADR-0092](0092-longhorn-for-hetzner-gpu-nodes.md) (`hetzner-k8s-gpu-1/2`, each
one RTX 4000 SFF Ada, 20475 MiB, driver 550 / CUDA 12.4) joined `home-remote`.
[ADR-0094](0094-generic-model-serving-orchestrator.md) allocates a whole card
per model — no MIG, no time-slicing — and [ADR-0095](0095-cluster-local-model-federation.md)
federates a served model to the gateway over the cluster network once (and only
once) [ADR-0101](0101-load-gate-before-federation-no-exceptions.md)'s load gate
has passed. Two catalog entries were enabled, one per card: `qwen3-5-2b` (vLLM,
federated through the gateway as `models-qwen3-5-2b-local`, reachable by every
gateway client) and `z-image-turbo` (LocalAI image generation —
[ADR-0102](0102-localai-instead-of-a-first-party-image-server.md) /
[ADR-0105](0105-pin-and-verify-the-localai-backend.md) /
[ADR-0106](0106-restore-the-localai-image-tier.md) — deliberately **not**
federated; LibreChat reaches it directly through the `z-image-proxy` b64
adapter, bypassing the gateway on purpose).

On 2026-09-15 the maintainer removed `hetzner-k8s-gpu-2` from the cluster,
halving the fleet to one card. ADR-0094's rule — one card, one model — had
never before had to arbitrate between two *already-enabled* models; until now
it had only ever queued a third behind two running ones. Verified live before
changing anything: gpu-1's single `nvidia.com/gpu` was already allocated to
`z-image-turbo`, and `qwen3-5-2b-main` sat at `0/1` available, stranded on the
node that had just been removed, with nowhere to reschedule. Every gateway
client routed to `models-qwen3-5-2b-local` was hitting a model with no pod
behind it — an immediate, live outage of the tier every client depends on, not
a hypothetical to weigh.

This also lands squarely on two things prior ADRs assumed wouldn't move.
[ADR-0092](0092-longhorn-for-hetzner-gpu-nodes.md) sized Longhorn's
`numberOfReplicas` at 2 explicitly *for* a 2-node pool ("Longhorn doesn't use
Raft/quorum, so a 2-node topology is not degraded, just less redundant"). And
[ADR-0114](0114-gpu-priority-preemption-over-a-serving-clock.md) chose priority
preemption over a serving clock while reasoning about "two cards, both claimed
24/7" — a fleet where a training run preempts *one of two* served tiers, not
the whole thing. The fleet catalog itself lives outside this repo since
[ADR-0129](0129-inference-catalog-moves-to-values-repo.md); the edits this
decision requires are split across `ai-helm-values` (the catalog, the LibreChat
config) and `ai-helm` (the `z-image-proxy` app entry).

## Decision

**The federated tier wins the card. Withdraw image generation end to end, drop
Longhorn to one replica, and flag — without editing — the ADR-0114 premise this
breaks.**

1. **One card, one model: `qwen3-5-2b` keeps it, `z-image-turbo` is disabled.**
   `qwen3-5-2b` is reachable by every gateway client (LibreChat, opencode,
   direct API); `z-image-turbo` was reachable by exactly one consumer, over a
   bypass path that exists specifically *because* it was never federated.
   Between "every client loses text/vision" and "one client loses image
   generation," the second is the smaller outage, and it is also the only one
   consistent with gpu-1 already having chosen it live. `ai-helm-values`
   `environments/prod/values/inference.yaml` sets `z-image-turbo.enabled:
   false`. The entry is kept verbatim rather than trimmed — it is the
   [ADR-0106](0106-restore-the-localai-image-tier.md)-measured, working
   configuration (32.4 s median / 1024×1024, 7985 MiB) — so re-enabling it is a
   one-line change, not a rebuild.

2. **The image-generation path is withdrawn whole, not half-disabled.** An
   adapter sitting in front of a Service with no endpoints is a 502 generator,
   and a picker entry pointing at a dead tool is a user-visible break — so
   every piece goes together in the same change:
   - `ai-helm-values` `environments/prod/values/librechat-app.yaml`: the
     `image-creator` modelSpec picker entry, the `image-creator` agent-seed
     entry, and the `IMAGE_GEN_OAI_*` env block are commented out, not
     deleted — the live `agent_id` and the shared local-model API key are only
     cleanly recoverable from git history if the lines stay in place.
     `configMaps.config-rollout.data.generation` bumps `12 → 13`, the
     unmounted-marker-ConfigMap contract that forces the LibreChat pods to pick
     up the config change (`charts/librechat-app/values.yaml:670-692`; pattern
     recorded in [ADR-0087](0087-librechat-app-config-to-values-repo.md)).
   - `ai-helm` `charts/apps/values.yaml:1409-1439` (specifically the `⚠️
     DISABLED` block at 1416–1426): `z-image-proxy` (the nginx/njs
     `response_format: b64_json` adapter, `charts/z-image-proxy/`) sets
     `enabled: false`.
   - ⚠️ **Removing the agent from the seed list does not delete the DB
     agent.** The agent-seed Job is a GET-by-name → PATCH upsert
     ([ADR-0086](0086-librechat-agent-fleet-and-gitops-seed.md)), not a
     declarative sync with pruning — dropping `image-creator` from
     `agentSeed` only stops *reconciling* it. The DB document for
     `agent_Oo2rOizVp7loelF7HMz9i` still exists; it is unreachable because its
     modelSpec entry — the picker's only path to it — is withdrawn in the same
     change, not because the agent document itself was removed.
   - `tools/check-model-catalogs.sh` passes on the result: one model served on
     the fleet, one federated cluster-local. `z-image-turbo` was never
     federated, so nothing is left advertising a gateway backend with no server
     behind it.

3. **Longhorn drops to a single replica, and the redundancy loss is stated
   plainly.** [ADR-0092](0092-longhorn-for-hetzner-gpu-nodes.md) scoped
   Longhorn to the GPU nodes only (they are the only nodes with no hcloud-csi)
   and set `numberOfReplicas: 2` for a 2-node pool. With one node, a 2-replica
   volume is unsatisfiable — Longhorn has nowhere to place the second replica,
   so every volume would sit permanently `degraded`, rebuilding forever against
   a topology that cannot host it. `ai-helm-values`
   `environments/prod/values/longhorn.yaml`:
   `persistence.defaultClassReplicaCount: 2 → 1`. Stated honestly rather than
   papered over: **one replica means the GPU node's disk is the only copy.**
   This is tolerable *only* because of what these volumes hold — re-fetchable
   model weights pulled from S3/HuggingFace, not primary data.
   ⚠️ Two operational traps this value change does not, by itself, close:
   existing volumes do **not** pick up a StorageClass replica-count change —
   moving an already-degraded 2-replica volume to healthy-at-1 needs an
   explicit `kubectl -n longhorn-system patch volumes.longhorn.io <name>
   --type=merge -p '{"spec":{"numberOfReplicas":1}}'` per volume. And
   Longhorn's `node-down-pod-deletion-policy` is `do-nothing`, so a pod that
   was stranded on the removed node (as `qwen3-5-2b-main` was) is not
   force-deleted for you — it has to be cleaned up by hand before the
   scheduler will place its replacement.

4. **ADR-0114's premise is now partly void — flagged, not revised.**
   [ADR-0114](0114-gpu-priority-preemption-over-a-serving-clock.md) chose GPU
   priority preemption (`inference-serving` at `-10` vs `mlops-training` at
   `1000`) over a serving clock, reasoning explicitly about "two cards, both
   claimed 24/7": a submitted training run preempted *one of two* served
   tiers, and the other kept serving through it. That arithmetic no longer
   holds. With one card and one model, the same preemption now takes down the
   fleet's **entire** inference-serving capacity every time a GPU training step
   is submitted — not a degraded fleet, an absent one, for as long as the
   workflow holds the card. ADR-0114 already listed "both models can go at
   once" as a negative; this makes that the *default* outcome rather than an
   edge case. ADRs are immutable once accepted, so ADR-0114's body is untouched
   here — this is a pointer, not an amendment. ADR-0114 should be revisited (a
   clock, a training-window notice, or an explicit accept-the-full-outage call)
   now that the trade-off it evaluated is materially sharper than the one it
   was written against.

5. **Rollback is symmetric and cheap once a second card exists.** Re-enable
   `z-image-turbo` in `inference.yaml`, uncomment the three LibreChat blocks in
   `librechat-app.yaml` (restoring the redacted API key from git history and
   bumping `config-rollout.generation` again), and flip `z-image-proxy.enabled`
   back to `true` in `charts/apps/values.yaml`. The 40Gi `z-image-turbo`
   weights PVC is `reclaimPolicy: Retain` (the Longhorn StorageClass default
   set in [ADR-0092](0092-longhorn-for-hetzner-gpu-nodes.md)), so the ~6.7 GB
   of already-downloaded weights survive the disable and a re-enable does not
   re-fetch them.

## Consequences

**Positive**

- The outage resolves in the direction that serves the most clients:
  `qwen3-5-2b` (text/vision, every gateway consumer) stays up; `z-image-turbo`
  (image generation, LibreChat only, via a deliberate bypass) is what's given
  up.
- No half-disabled state anywhere. Every consumer of the withdrawn path — the
  picker entry, the DB agent's only route to being reachable, the env block,
  the proxy — goes down together, so there is no adapter left fronting an
  endpoint-less Service and no picker entry that quietly 502s.
- `tools/check-model-catalogs.sh` confirms the fleet is internally consistent
  after the change: nothing federated is missing a server, nothing
  served-but-dead is still advertised.
- Rollback is one flag per file plus three uncomments — no re-seeding and no
  re-fetching weights, because the PVC was never deleted.

**Negative**

- **Real capability loss.** Self-hosted image generation is unavailable to
  every LibreChat user until a second card exists. This is a user-visible
  regression, not a formality.
- **Real redundancy loss on Longhorn.** A single replica means a disk failure
  on the one remaining GPU node loses the cache outright, forcing a full
  re-fetch of `qwen3-5-2b`'s weights from scratch. Accepted for the same reason
  [ADR-0092](0092-longhorn-for-hetzner-gpu-nodes.md) already accepted it at 2
  replicas — the data is re-fetchable and not primary — one notch further.
- **ADR-0114's trade-off is now categorically worse than what it evaluated**,
  and nothing in this ADR fixes that — it only records that the assumption
  underneath it changed. Until ADR-0114 is revisited, every submitted MLOps
  training step takes the entire fleet's serving capacity with it: no window,
  no notice, and — per ADR-0114's own accepted consequences — no drain.
- The agent-seed Job's GET-by-name/PATCH shape means the `image-creator` DB
  agent is now an orphaned document rather than a cleanly removed one — a
  minor but real piece of state that outlives the decision that made it
  unreachable.

**Neutral / follow-ups**

- Revisit [ADR-0114](0114-gpu-priority-preemption-over-a-serving-clock.md)
  against the 1-card fleet. The options it already weighed and rejected (a
  KEDA cron clock, a hand-rolled CronJob, permanently favoring one workload
  class) all read differently once preemption no longer costs "one of two
  tiers" but "all service."
- Raise Longhorn's `defaultClassReplicaCount` back to 2 (and reconsider the
  chart default of 3) the moment a second GPU node rejoins — and remember the
  per-volume `numberOfReplicas` patch is still required for volumes that
  already exist at that point; they do not pick the StorageClass change up on
  their own.
- The `image-creator` DB agent document is inert but not deleted. A future
  cleanup pass could remove it outright if image generation is not coming back
  on a predictable timeline; left alone for now because the seed Job's
  mechanism makes that a deliberate extra step, not a side effect of this
  change.
- No alerting exists today for "the fleet's only served model was preempted" —
  the same gap ADR-0114 already flagged as a follow-up, now with a larger
  blast radius per occurrence.

## Alternatives considered

- **Keep `z-image-turbo`, disable `qwen3-5-2b` instead.** Rejected on reach
  alone: `qwen3-5-2b` is federated to every gateway client; `z-image-turbo`
  served exactly one consumer through a deliberate bypass. Losing the model
  every client depends on in order to keep the one only LibreChat used is the
  wrong trade by a wide margin.
- **Manually alternate the two models on the single card** (swap which one is
  `enabled` depending on demand). Rejected: this is exactly the "one GPU, swap
  forever" toil [ADR-0094](0094-generic-model-serving-orchestrator.md) was
  written to eliminate, reintroduced one card after that ADR shipped. The
  catalog is a declarative one-entry-per-model shape; a manual swap dance
  fights it rather than using it.
- **Leave `z-image-turbo` `enabled: true` and let it queue behind `qwen3-5-2b`.**
  Rejected: it does not queue politely — it was already scheduled and holding
  the only card, so leaving it enabled means it actively blocks `qwen3-5-2b`
  from scheduling at all. This is the state that was actually observed live
  and is what forced the decision in the first place.
- **Leave Longhorn at `numberOfReplicas: 2` and accept a permanently-degraded
  status.** Rejected for the same reason
  [ADR-0092](0092-longhorn-for-hetzner-gpu-nodes.md)'s own alternatives section
  rejected the equivalent choice for the 3-replica-on-2-nodes case: a
  permanently "degraded" healthy state is alerting/dashboard noise for zero
  actual redundancy benefit.
- **Fold an ADR-0114 revision into this change.** Rejected: ADRs are immutable
  once accepted, and a proper revisit needs its own evaluation of what
  replaces or augments preemption on a 1-card fleet — that is follow-up work,
  not a paragraph bolted onto a decommissioning record. This ADR flags the
  sharpened trade-off and stops there.

## Related

- Amends: [ADR-0092](0092-longhorn-for-hetzner-gpu-nodes.md) (2-replica
  topology sized for 2 nodes, now 1), [ADR-0106](0106-restore-the-localai-image-tier.md)
  (the image tier it restored is disabled, not reverted — chart and config
  untouched)
- Sharpens without editing: [ADR-0114](0114-gpu-priority-preemption-over-a-serving-clock.md)
  — its "two cards, both claimed 24/7" premise no longer holds; revisit
  recommended, not performed here
- Builds on: [ADR-0094](0094-generic-model-serving-orchestrator.md) (one card,
  one model), [ADR-0095](0095-cluster-local-model-federation.md) (federation
  shape — why `z-image-turbo` had a direct-bypass path to begin with),
  [ADR-0101](0101-load-gate-before-federation-no-exceptions.md) (serving ≠
  federating), [ADR-0102](0102-localai-instead-of-a-first-party-image-server.md) /
  [ADR-0105](0105-pin-and-verify-the-localai-backend.md) (the LocalAI engine
  and its pinned backend, unaffected by this disable), [ADR-0129](0129-inference-catalog-moves-to-values-repo.md)
  (the catalog this decision edits lives in `ai-helm-values`, not here),
  [ADR-0086](0086-librechat-agent-fleet-and-gitops-seed.md) (the
  GET-by-name/PATCH agent-seed mechanism), [ADR-0087](0087-librechat-app-config-to-values-repo.md)
  (the `config-rollout` marker-ConfigMap contract)
- Files: `charts/apps/values.yaml:1409-1439` (`z-image-proxy` app entry, disabled
  block at 1416–1426), `charts/z-image-proxy/`, `charts/librechat-app/values.yaml:670-692`
  (`config-rollout` marker contract)
- Values repo (`ai-helm-values`, private): `environments/prod/values/inference.yaml`
  (`z-image-turbo.enabled`), `environments/prod/values/librechat-app.yaml`
  (modelSpec, agent-seed entry, `IMAGE_GEN_OAI_*`, `config-rollout.generation`),
  `environments/prod/values/longhorn.yaml` (`persistence.defaultClassReplicaCount`)
- Verification: `tools/check-model-catalogs.sh`
