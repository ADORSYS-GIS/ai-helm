#!/bin/sh
# check-model-catalogs.sh — guard the two halves of a self-hosted model deployment.
#
# A model needs entries in TWO places, and that split is deliberate (see the
# header of charts/inference/values.yaml):
#
#   charts/inference/values.yaml   models:    → it RUNS on a GPU
#   charts/ai-models/values.yaml   models:    → users can ROUTE to it
#                                  backends:  → where the gateway sends traffic
#
# Serving without federating is a legitimate and useful state: it is how a model
# gets deployed and measured before anyone can reach it. The reverse is not. A
# federated model with no server behind it 503s every request, and a federated
# backend pointing at the wrong in-cluster Service fails only at request time —
# long after the ArgoCD sync went green. Both are exactly the kind of mistake a
# hurried model swap makes, so they are checked here instead of in production.
#
# Enforced — ONE invariant, chosen because it needs no exception list:
#
#   Every enabled ai-models backend whose hostname is in the `inference`
#   namespace must resolve to a Service that an enabled charts/inference
#   entry actually creates.
#
# That single rule catches every direction of drift that matters: a federation
# left enabled after its server was disabled, a model renamed on one side only,
# and a backend typo. The complementary case ("model enabled in ai-models but no
# backend declared") is already a hard render failure in charts/ai-model, via its
# `backendsInventory` guard — no need to duplicate it here.
#
# Deliberately NOT enforced: "every `*-local` model has an inference entry".
# The legacy `model-serving-*` charts still serve several `*-local` models from
# the OTHER cluster (admin@homeos) with public `*--poc.ssegning.com` backends, so
# that rule would fail permanently on a correct repo. Scoping to cluster-local
# hostnames distinguishes the two generations without a maintained allowlist.
#
# Implementation note: this reads RENDERED Helm output rather than the values
# files, using only grep/sed — no yq, no Python, nothing to install. Reading the
# render means the check sees what will actually be deployed (defaults applied,
# template logic run), and it stays correct if either chart's values shape
# changes. Both charts must have their dependencies built (`helm dep build`).

set -eu

SERVING_CHART="charts/inference"
AI_MODELS_CHART="charts/ai-models"
# Must match charts/inference/values.yaml argocd.destination.namespace.
INFERENCE_NS="inference"
# Fixed release name so the generated child-app prefix is predictable.
REL="chk"

for d in "$SERVING_CHART" "$AI_MODELS_CHART"; do
  [ -d "$d" ] || { echo "check-model-catalogs: $d not found — run from the repo root" >&2; exit 2; }
done
command -v helm >/dev/null 2>&1 || { echo "check-model-catalogs: helm is required" >&2; exit 2; }

render() {
  if ! helm template "$REL" "$1" 2>/dev/null; then
    echo "check-model-catalogs: failed to render $1 (try: helm dep build $1)" >&2
    exit 2
  fi
}

serving_out=$(render "$SERVING_CHART")
aimodels_out=$(render "$AI_MODELS_CHART")

# Models actually being served. Each generated child is `<REL>-<modelName>`, and
# the model name is also the Service name (fullnameOverride).
served=$(printf '%s\n' "$serving_out" \
  | sed -n "s/^ *- appName: \"$REL-\(.*\)\"$/\1/p" | sort -u)

fail=0
note() { printf '  x %s\n' "$1" >&2; fail=1; }

# ── A cluster-local backend must point at a Service that exists ──────────────
locals=$(printf '%s\n' "$aimodels_out" \
  | sed -n "s/^ *hostname: \([A-Za-z0-9-]*\)\.$INFERENCE_NS\.svc\.cluster\.local$/\1/p" | sort -u)

for svc in $locals; do
  if ! printf '%s\n' "$served" | grep -qx "$svc"; then
    note "ai-models has a backend pointing at '$svc.$INFERENCE_NS.svc.cluster.local',
    but no enabled charts/inference entry creates a Service named '$svc'.
    The model name must match the backend hostname exactly."
  fi
done

if [ "$fail" -ne 0 ]; then
  printf '\ncheck-model-catalogs: the serving catalog and the gateway catalog disagree.\n' >&2
  printf 'See charts/inference/values.yaml and inference-ops how-to/add-a-model.md.\n' >&2
  exit 1
fi

n_served=$(printf '%s\n' "$served" | grep -c . || true)
n_local=$(printf '%s\n' "$locals" | grep -c . || true)
echo "check-model-catalogs: OK ($n_served served on the GPU fleet, $n_local federated cluster-local)"

# Informational, never a failure: a served-but-unfederated model is the normal
# state while a new model is being load-gated (inference-ops how-to/measure-a-model.md).
for svc in $served; do
  if ! printf '%s\n' "$locals" | grep -qx "$svc"; then
    echo "  note: '$svc' is served but not federated — no user can route to it yet."
  fi
done
