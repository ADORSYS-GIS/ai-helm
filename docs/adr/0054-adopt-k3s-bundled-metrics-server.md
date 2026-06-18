# ADR-0054: Adopt the k3s-bundled metrics-server instead of shipping our own

**Status:** Accepted
**Date:** 2026-06-19
**Deciders:** @stephane-segning

## Context

We shipped a GitOps `metrics-server` (the upstream kubernetes-sigs chart, 2
replicas, via a `charts/apps` app entry → ArgoCD app `aii-metrics-server`). But
k3s **also** bundles a metrics-server addon, reconciled by the k3s addon manager
from on-disk manifests under `/var/lib/rancher/k3s/server/manifests/metrics-server/`.
The two collide on the shared object names `Deployment/metrics-server` and
`Service/metrics-server` in `kube-system`:

- The k3s addon keeps re-applying its Deployment, whose pod carries only the label
  `k8s-app=metrics-server`.
- Our GitOps Service selects `app.kubernetes.io/name` + `app.kubernetes.io/instance`
  + `k8s-app`, so it never matches the k3s pod → **empty endpointslice** →
  `v1beta1.metrics.k8s.io` reports `MissingEndpoints` ("no addresses with port name
  https") → `kubectl top` and HPAs break. This recurred on essentially every sync
  and after node restarts (the `aii-metrics-server` app sat permanently `OutOfSync`/
  `Progressing` because the bundled Deployment squatted the name).

The "correct per hetzner-k8s ADR-0015" remediation — `--disable metrics-server` on
the k3s server plus a control-plane node `terraform … -replace` (because
`ignore_changes=[user_data]` keeps an existing CP on its old start args) — is heavy,
touches node provisioning, and hasn't held across restores. Meanwhile the k3s
metrics-server is genuinely **healthy**: its pod is `Ready` (the `metric-storage-ready`
gate only passes once it has metrics), `/readyz` and `/livez` return `ok`, and it
scrapes the kubelets. The only thing wrong is that our Service was shadowing it.

## Decision

**Stop shipping a GitOps metrics-server. Adopt the k3s-bundled one as the cluster's
metrics provider.** Remove the `metrics-server` entry from `charts/apps/values.yaml`
(replaced by an explanatory comment). With our app gone, ArgoCD prunes our
`Service`/`APIService`, and the k3s addon manager re-applies its own
`metrics-server-service.yaml` (selector `k8s-app=metrics-server`, which **does**
match the running pod) and `metrics-apiservice.yaml` → endpoints populate → the
metrics API recovers. No node reprovision needed.

This effectively reverses the hetzner-k8s ADR-0015 intent (disable the bundled addon
in favour of a GitOps copy) **for the metrics-server specifically** — we accept the
k3s default here rather than fight the addon manager.

## Consequences

**Positive**
- The metrics API stops breaking on every sync / node restart — no more
  `MissingEndpoints`, `kubectl top`/HPA stay up.
- No control-plane node reprovision, no `--disable metrics-server` dependency.
- One less app to keep in lockstep with release tags.

**Negative**
- We lose GitOps control of metrics-server config: the `--kubelet-insecure-tls`,
  `--kubelet-preferred-address-types`, `--metric-resolution=15s` args, the 2-replica
  HA, the PDB, and resource requests are now whatever k3s ships. Tuning them means
  changing the k3s server manifests in `hetzner-k8s`, not this repo.
- The intermittent kubelet-scrape `context deadline exceeded` errors (mostly CP node
  `10.0.0.10` and worker-2 — a kubelet-reachability issue, not a metrics-server bug)
  remain and are no longer ours to tune from here. They do not flip the pod out of
  `Ready`.

**Neutral / follow-ups**
- If we ever need bespoke metrics-server config (HA replicas, custom scrape timeout),
  the path is the hetzner-k8s ADR-0015 route: `--disable metrics-server` + CP node
  `-replace`, then re-add a GitOps app. Write a superseding ADR if so.
- Live cutover (one-time, deploys with the next release once the root is repointed):
  ArgoCD prunes our objects on sync; confirm `v1beta1.metrics.k8s.io` goes
  `Available=True` and `kubectl top nodes` works. The audit doc §4 "delete + re-own"
  remediation is now obsolete.

## Alternatives considered

- **Honour ADR-0015 — keep our GitOps metrics-server, durably kill the k3s addon**
  (`--disable metrics-server` on the k3s server + `terraform -replace` the CP node).
  Rejected for now: heavy, touches node provisioning, and it hadn't survived
  restores/restals — the addon kept coming back. Still the right path *if* we later
  need config we can't get from the bundled one.
- **Relabel/realign our Service selector to match the k3s pod.** Rejected: a hack
  that leaves two controllers fighting over the same Deployment, and ArgoCD would
  still churn against the addon-owned objects.

## Related

- Docs: `docs/2026-06-07-observability-datasource-audit.md` §4 (the collision +
  the now-obsolete remediation), `CLAUDE.md` (the recurring-gotcha note).
- Charts/files touched: `charts/apps/values.yaml` (metrics-server entry removed).
- Supersedes (cross-repo, intent only): hetzner-k8s ADR-0015 for metrics-server.
