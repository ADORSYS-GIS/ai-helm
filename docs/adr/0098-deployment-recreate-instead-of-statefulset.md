# ADR-0098: Run model servers as a Deployment with `Recreate`, not a StatefulSet

**Status:** Accepted
**Date:** 2026-07-26
**Deciders:** @stephane-segning

## Context

[ADR-0030](0030-merge-model-and-proxy-into-one-statefulset-bjw.md) chose a
single-replica **StatefulSet** for the model workload, and explicitly considered
the alternative:

> **A Deployment with two containers (not a StatefulSet)** — equivalent for
> `replicas: 1` (would need `strategy: Recreate` for the single-GPU guarantee).

They are equivalent for the property ADR-0030 cared about — never two model
containers on one GPU. They are **not** equivalent in failure.

A StatefulSet defaults to `podManagementPolicy: OrderedReady`, under which the
controller will not replace a pod that is not Ready. So a **crash-looping pod
blocks its own fix**: the corrected chart merges, ArgoCD syncs, `.spec.template`
carries the new arguments, and the pod goes on running the old ones indefinitely.
The only visible signal is that `.status.currentRevision` differs from
`.status.updateRevision`; to an operator it looks like the merge did nothing.

This is documented Kubernetes behaviour, not a bug — the StatefulSet
"Forced rollback" documentation says that after a bad configuration you must
delete the pod by hand. It bit us for real: a vLLM model was crash-looping on a
bad argument, the fix was merged, and nothing changed until the pod was deleted
manually. That is precisely the moment when an extra manual step is least
welcome, and it will recur every time a bad config reaches a model.

Critically, **we use no StatefulSet-only feature**. Verified on the live objects:
`volumeClaimTemplates` is empty (the weights PVC is our own RWX claim, mounted via
`existingClaim`), there is no ordinal identity requirement, and no stable network
name is needed — the Service selects on labels. ADR-0029, before ADR-0030, in fact
used a `Deployment` + `Recreate`.

## Decision

Render the model workload as a **`Deployment` with `strategy: Recreate`**.

`Recreate` is load-bearing, not cosmetic: it fully terminates the old pod before
creating the replacement, so two pods never contend for the single
`nvidia.com/gpu: 1`. Under `RollingUpdate` with any surge, the new pod would sit
`Pending` waiting for a card the old pod still holds while the old pod waits for
the new one to be Ready — a deadlock. This is the same single-instance guarantee
ADR-0030 obtained from ordinal semantics, reached a different way.

What changes is the failure mode: a Deployment has no readiness gate before
replacing a pod, so a bad configuration **self-heals on the next merge** instead
of requiring `kubectl delete pod`.

This **amends ADR-0030's workload-shape choice only**. Everything else there
stands: one bjw-template-rendered workload, `replicas: 1`, the hybrid chart shape,
the seed Job as an ArgoCD hook. (ADR-0030's Caddy sidecar is separately gone —
[ADR-0095](0095-cluster-local-model-federation.md)/[ADR-0097](0097-engine-agnostic-serving-hardening.md).)

## Consequences

**Positive**

- A bad config is fixed by merging a fix. No manual `kubectl delete pod`, and no
  "the merge did nothing" confusion in the middle of an incident.
- The single-GPU invariant is now stated explicitly (`strategy: Recreate`) rather
  than inherited implicitly from ordinal semantics.
- One fewer piece of Kubernetes trivia a junior must know to operate the fleet.

**Negative**

- Pod names lose their stable ordinal: `<model>-main-0` becomes
  `<model>-main-<hash>-<rand>`. Every doc and runbook command that named a pod
  directly has been rewritten to `deploy/<model>-main`, which is more robust
  anyway. Anyone with the old form in muscle memory or a script will notice.
- Switching kind means ArgoCD prunes the StatefulSet and creates a Deployment: a
  one-time restart of both models, ~1–2 min each while weights reload.
- `Recreate` means the downtime is unavoidable by construction. It already was
  with one replica on one GPU; it is now explicit.

**Neutral / follow-ups**

- If a model ever needs genuine HA, neither shape helps — that needs a second card
  and a router, not a workload-kind change.
- `podManagementPolicy` is immutable on a StatefulSet, so "just set `Parallel`"
  would have required recreating the object anyway, for a behaviour that is less
  clearly specified than `Recreate`.

## Alternatives considered

- **Keep the StatefulSet, set `podManagementPolicy: Parallel`** — rejected. The
  field is immutable (so the object must be recreated regardless), and its effect
  on a stuck *update* is far less clearly specified than `Recreate`'s. Choosing
  the shape whose semantics are unambiguous is worth more than avoiding a
  one-time recreate.
- **Keep the StatefulSet and document `kubectl delete pod`** — rejected; it was
  already documented, in a runbook, and the step was still missed under pressure.
  A manual remediation that is only needed during incidents is the one most likely
  to be forgotten.
- **Automate the delete** (a controller or sync hook that removes stuck pods) —
  rejected as machinery to paper over a workload kind we had no reason to use.
- **`RollingUpdate` with `maxSurge: 0`** — this would also avoid two pods, but a
  Deployment's `Recreate` states the intent directly, and `maxSurge: 0` invites a
  future edit that quietly reintroduces the deadlock.

## Related

- Amends [ADR-0030](0030-merge-model-and-proxy-into-one-statefulset-bjw.md)
  (workload shape only); returns to the shape [ADR-0029](0029-self-hosted-model-plain-deployment.md) used
- Charts: `charts/model-serving/templates/_helpers.tpl`,
  `charts/model-server/ci/*-values.yaml`
- Docs: `docs/patterns/self-hosted-model-serving.md` §8; `inference-ops`
  runbooks and how-tos rewritten to `deploy/<model>-main`
