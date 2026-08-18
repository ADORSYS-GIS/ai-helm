# ADR-0132: SBOM + cosign signing for OCI-published Helm charts

**Status:** Proposed
**Date:** 2026-08-17
**Deciders:** @Guy-Ghis

## Context

The historical delivery path for this repo used tag-based releases
(ADR-0031) — `release-helm-charts.yml` + chart-releaser + `docs/releasing.md`.
That model was retired and superseded by **continuous delivery** (ADR-0055):
on every merge to `main`, `publish-charts-oci.yml` packages each changed chart
and pushes it to `oci://ghcr.io/adorsys-gis/charts`, where child Applications
float on a semver range (ADR-0082). Under that model the release artifact is
the OCI Helm chart itself.

Story #136 ("Add Trivy, Gitleaks, SBOM, and cosign to CI/CD") already landed the
scanning half (#160): Gitleaks + Trivy via the org-shared
`ai-governance/security-gates.yml` and a deterministic Trivy config scan of
rendered manifests in `release-helm-charts.yml`. The remaining child #161 asks
for **SBOM generation and cosign signing** on the release path. Neither exists
today: charts are pushed unsigned, with no bill of materials attached. While
cosign signing of *container images* is already proven in the org
(`lightbridge-code-intelligence/image-pipeline.yml` signs each image keylessly,
and argocd-image-updater verifies those signatures before write-back — itself a
ADR-0055 decision), the *chart artifacts themselves* have no provenance.

#161 was drafted against the now-retired tag-based pipeline; its source of truth
must be reconciled to the ADR-0055 OCI path, which is where this work lands.

## Decision

**Adopt keyless Sigstore cosign signing + SBOM attachment for every changed
Helm chart published by `publish-charts-oci.yml`, with the SBOM scoped to the
container images the chart's rendered manifests deploy.**

- **Signing:** keyless (Sigstore bundled / GitHub Actions OIDC), mirroring the
  exact mechanics already used for images in `lightbridge-code-intelligence`
  (`sigstore/cosign-installer@v3` + `id-token: write` + `cosign sign --yes` on
  the pushed artifact). No private key to store or rotate.
- **SBOM:** a per-chart CycloneDX 1.5 inventory of the container image references
  that `helm template` (deterministic, `--kube-version 1.31`, the same render the
  Trivy scan uses) emits from the chart's manifests — `tools/oci-chart-sbom.sh`.
  Attached to the chart artifact with `cosign attach sbom`. SBOM generation is
  **best-effort**: a chart that cannot render standalone (an orchetsrator, or a
  leaf that needs injected values) yields an empty inventory but is still signed.
- **Scope of the SBOM** is deliberately the *inventory* of what the chart ships
  (the image refs), not the transitive virtual-package SBOM of each image — the
  org already scans images with Trivy and cosign-verifies first-party images at
  the image-updater boundary, so that layer is covered elsewhere.

## Consequences

**Positive**

- Release artifacts become **inventoriable and verifiable**: a consumer can
  `cosign verify` a chart and pull its attached SBOM to see exactly which images
  it deploys — the #161 acceptance criteria, delivered on the live CD path.
- Keyless signing means **no key-management burden** and a verifiable identity
  bound to the publishing workflow (`certificate-identity` =
  `publish-charts-oci.yml`), consistent with how the org already signs images.
- SBOM-from-render is cheap, deterministic and needs no registry pulls or image
  scanning at publish time — it reuses the same rendering the Trivy gate already
  relies on.

**Negative**

- **Helm and ArgoCD do not natively *enforce* chart cosign signatures today.** A
  chart signature is verification/provenance for a human or an out-of-band gate,
  not an admission-time block. This ADR deliberately does **not** claim in-cluster
  enforcement (the ticket lists it as out of scope; container-level enforcement
  already exists via image-updater). Overstating this as a security boundary would
  be wrong.
- Charts that render no images (orchestrators like `coder`, `homepage`) attach an
  essentially-empty SBOM — low signal for those, though the signature still proves
  provenance.
- Adds a couple of steps and OIDC-permission surface to the publish workflow;
  cosign/OCI-attach behavior must be watched on the first few merges after cutover.

**Neutral / follow-ups**

- SBOM tooling emits CycloneDX 1.5; consumers wanting SPDX can convert.
- The `.trivyignore.yaml`/scan story is unchanged — this ADR is additive to #160.
- If the org later wants admission-time chart verification, that is a new decision
  (ArgoCD/controller capability), out of scope here.

## Alternatives considered

- **Key-based cosign (a stored keypair as an Actions secret)** — rejected. It
  buys a stable signing identity but at the cost of key storage, rotation and
  leak-mitigation, for no benefit here; keyless already binds identity to the
  publishing workflow and matches the org's proven image-signing pattern.
- **SBOM of the packaged chart `.tgz` (a Trivy/Syft filesystem scan)** — rejected.
  A Helm chart is YAML/templates with no OS or packages, so an FS SBOM is
  near-zero signal. The images the chart deploys are the actual attack surface.
- **Full per-image transitive SBOM aggregation at publish time** — rejected as
  scope creep + a CI cost/credential burden; image-level scanning/verification
  already lives at the image boundary (Trivy scan + cosign-gated image-updater).
- **Slot into the retired `release-helm-charts.yml` tag pipeline** — rejected: the
  tag model is superseded by ADR-0055 and its chart-releaser branch only runs on
  manual `workflow_dispatch`. The real release path is `publish-charts-oci.yml`.

## Related

- Docs (the *how*): `docs/patterns/supply-chain.md`, `docs/continuous-delivery.md`
- Files: `.github/workflows/publish-charts-oci.yml`, `tools/oci-chart-sbom.sh`
- Implements child ticket: #161 of story #136 (epic #144)
- Builds on: [0055](./0055-oci-charts-and-image-updater-writeback-to-values-repo.md),
  [0082](./0082-release-please-changelog-and-minor-major-floor.md); adopts the org's
  image-signing precedent from `lightbridge-code-intelligence/image-pipeline.yml`;
  supersedes the tag-based SBOM/signing assumption of the retired
  [0031](./0031-tag-based-deploys.md)
