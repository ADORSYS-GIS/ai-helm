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
          | jq -sc '[ .[] | .. | objects | select(has("containers") or has("initContainers")) | (.containers[]?, .initContainers[]?) | .image // empty ] | unique' 2>/dev/null \
    || echo '[]'
  )"
fi
rm -f "$rendered"

number_of_images=$(jq 'length' <<< "$images_json")

# Split `repo:tag` / `repo@sha256:…` into purl-able name+version. Split on the
# LAST `:` so registry ports (`localhost:5000/foo:1.0` → name `localhost:5000/foo`,
# version `1.0`) don't corrupt the name; digests (`repo@sha256:…`) are split on `@`.
components_json="$(
  jq -c '
    [ .[] as $ref
      | if ($ref | contains("@")) then
          ($ref | split("@")) as $p
          | { "name": $p[0], "version": ($p[1] // "latest"), "raw": $ref }
        else
          ($ref | split(":")) as $p
          | if ($p|length) == 1 then
              { "name": $ref, "version": "latest", "raw": $ref }
            else
              { "name": ($p[0:-1] | join(":")), "version": $p[-1], "raw": $ref }
            end
        end
    ]
    | map( { type: "container", name: .name, version: .version,
             purl: ("pkg:oci/" + .name + "@" + .version) } )
  ' <<< "$images_json"
)"

# CycloneDX requires serialNumber to be a valid `urn:uuid:`. Prefer uuidgen;
# fall back to the kernel's v4 UUID source, then a /dev/urandom-derived v4 UUID
# so the value is always a well-formed UUID even on hosts without uuidgen.
serial="$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || {
  hex="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
  printf '%s-%s-4%s-8%s-%s' "${hex:0:8}" "${hex:8:4}" "${hex:13:3}" "${hex:17:3}" "${hex:20:12}"
})"
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
