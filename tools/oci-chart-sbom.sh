#!/usr/bin/env bash
#
# Generate a CycloneDX SBOM for a published Helm chart whose "packages" are the
# container images the chart's rendered manifests actually deploy.
#
# A Helm chart is just YAML/templates — it has no OS/packages of its own. The
# meaningful SBOM surface is the set of container images those templates
# reference when rendered. This script renders the chart with `helm template`
# (deterministic, `--kube-version 1.31` like the Trivy render in
# release-helm-charts.yml), extracts the image refs from the emitted manifests,
# and emits a CycloneDX 1.5 JSON SBOM with one `component` per unique image.
#
# Usage:
#   oci-chart-sbom.sh <chart-dir> <release-name> <out-sbom.json>
#
# Exits 0 and writes an EMPTY (components: []) inventory if the chart cannot be
# rendered standalone — the caller is expected to treat SBOM generation as
# best-effort and never let it block the chart publish. Scanning the referenced
# images for their transitive package SBOMs is deliberately left to a dedicated
# image-level gate (the org already cosign-verifies first-party images at the
# image-updater boundary); this document inventories WHAT the chart ships.
#
# Depends on: helm, yq (mikefarah), jq.

set -euo pipefail

chart_dir="$1"
release_name="$2"
out_json="$3"

chart_name=$(yq e '.name' "$chart_dir/Chart.yaml")
chart_version=$(yq e '.version' "$chart_dir/Chart.yaml")
rendered="$(mktemp)"

# Collect unique container image references from rendered Pod specs. Matches the
# common shapes emitted by the bjw-app-template / common lib: a bare `image:`
# under `containers`/`initContainers` at the standard `.spec.template.spec.containers`
# and (Job/CronJob) `.spec.jobTemplate.spec.template.spec.containers` depths.
images_json="[]"
if helm template "$release_name" "$chart_dir" --kube-version 1.31.0 --skip-tests >"$rendered" 2>/dev/null; then
  images_json="$(
    yq -o=json '.' "$rendered" 2>/dev/null \
          | jq -sc '[ .[] | .. | objects | select(has("containers")) | .containers[]? | .image // empty ] | unique' 2>/dev/null \
    || echo '[]'
  )"
fi
rm -f "$rendered"

number_of_images=$(jq 'length' <<< "$images_json")

# Split `repo:tag` / `repo@sha256:…` into purl-able name+version.
components_json="$(
  jq -c '
    [ .[] as $ref
      | . as $tmp
      | ( if ($ref | contains("@")) then ($ref | split("@")) else ($ref | split(":")) end ) as $parts
      | { "name": $parts[0],
          "version": (if ($parts|length) > 1 then $parts[1] else "latest" end),
          "raw": $ref }
    ]
    | map( { type: "container", name: .name, version: .version,
             purl: ("pkg:oci/" + .name + "@" + .version) } )
  ' <<< "$images_json"
)"

serial="$(uuidgen 2>/dev/null || echo "$RANDOM-$RANDOM-$RANDOM-$RANDOM")"
timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

jq -n \
  --argjson comps "$components_json" \
  --arg bom "CycloneDX" \
  --arg spec "1.5" \
  --arg serial "urn:uuid:$serial" \
  --arg ts "$timestamp" \
  --arg name "$chart_name" \
  --arg ver "$chart_version" \
  '{ bomFormat: $bom,
     specVersion: $spec,
     serialNumber: $serial,
     version: 1,
     metadata: {
        timestamp: $ts,
        component: { type: "library", name: $name, version: $ver,
                     purl: ("pkg:oci/" + $name + "@" + $ver) },
        tools: [ { vendor: "ADORSYS-GIS", name: "oci-chart-sbom", version: "1.0.0" } ]
     },
     components: $comps }' > "$out_json"

echo "SBOM for $chart_name@$chart_version: $number_of_images image component(s) → $out_json"
