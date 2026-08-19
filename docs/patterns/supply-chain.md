# Supply-chain: SBOM + cosign verification for published charts (ADR-0132)

Every changed Helm chart published to `oci://ghcr.io/adorsys-gis/charts` by
[`publish-charts-oci.yml`](../../.github/workflows/publish-charts-oci.yml) is now:

1. **Signed** with keyless Sigstore cosign (OIDC), identity bound to the
   publishing workflow.
2. Given a **CycloneDX 1.5 SBOM** (best-effort) listing the container images its
   rendered manifests deploy, carried as the predicate of a **signed in-toto
   attestation** via `cosign attest --type cyclonedx`.

The **why** is [ADR-0132](../adr/0132-sbom-and-cosign-sign-oci-charts.md). This
page is the **how** — what a consumer needs to verify a chart and its SBOM.

> ⚠️ **Honest scope.** Helm and ArgoCD do **not** enforce chart cosign signatures
> at admission time today. What this buys you is **provenance and verifiability**:
> you can confirm who published a chart and that its bytes are un-tampered, and
> see exactly which images it deploys. Enforcement at the *container* level
> already happens via argocd-image-updater (which cosign-verifies first-party
> images before write-back, ADR-0055) + the Trivy scan gate (#160). Do not treat a
> chart signature as an in-cluster security boundary.

## What gets produced

For each changed chart `C` at version `V`, on a merge to `main`:

- the OCI artifact `oci://ghcr.io/adorsys-gis/charts/C:V` (as before, ADR-0055);
- a **keyless `.sig` signature** on every chart (the uniform provenance baseline);
- a **signed in-toto attestation** (`.att` accessor) whose `predicate` holds the
  CycloneDX SBOM `C-V.sbom.json`, when the chart could be rendered (see below).

So every chart carries a `.sig`; charts with a renderable SBOM additionally carry
an `.att`.

## Verifying a published chart

Charts are addressed by **version tag** (`ghcr.io/adorsys-gis/charts/<C>:<V>`),
not digest. This matches the delivery model (ADR-0055/0082 — child Applications
float on a semver range) and is the appropriate scheme here: cosign resolves the
tag to its digest at verify time and binds the signature/attestation to those
exact bytes, so the tag adds no tamper surface. The compliance angle of the
platform roadmap (SOC 2 Type II / AIBOM) is about *content provenance* — which
the signed SBOM attestation provides — not digest-addressing of the chart.

Every chart carries a `.sig`, so the baseline check is `cosign verify` (works for
**all** charts):

```bash
# signature (keyless) — identity is pinned to the publishing workflow
cosign verify \
  --certificate-identity-regexp '^https://github\.com/ADORSYS-GIS/ai-helm/\.github/workflows/publish-charts-oci\.yml@refs/heads/main$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/adorsys-gis/charts/<C>:<V>
```

For charts with a renderable SBOM (which also carry an `.att`), verify the SBOM
attestation too:

```bash
# SBOM attestation (keyless) — only for charts that rendered an SBOM (.att present)
cosign verify-attestation \
  --certificate-identity-regexp '^https://github\.com/ADORSYS-GIS/ai-helm/\.github/workflows/publish-charts-oci\.yml@refs/heads/main$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --type cyclonedx \
  ghcr.io/adorsys-gis/charts/<C>:<V>
```

A successful run prints the certificate subjects + the verified digest.

## Pulling the SBOM (attestation)

The SBOM is carried as the **predicate of a signed in-toto attestation** (via
`cosign attest --type cyclonedx`), so pulling it is done with the attestation
commands:

```bash
# download the signed attestation (SBOM is the predicate)
cosign download attestation ghcr.io/adorsys-gis/charts/<C>:<V>
```

The attestation's `predicate` holds the CycloneDX SBOM listing one `container`
component per unique image the chart's deterministically-rendered manifests
reference (default tag `latest` when the manifest omits one).

## What "best-effort" SBOM means

`tools/oci-chart-sbom.sh` renders the chart with `helm template --kube-version
1.31.0 --skip-tests` (the same deterministic-render contract the Trivy gate uses)
and reads the emitted `image:` refs. Charts that render **no** images — the
orchestrators (`coder`, `homepage`, …) that emit ArgoCD `Application` CRs, and
leaves that need injected values — produce an **empty `components: []` SBOM**. The
chart is still signed; only the SBOM content is thin. This is by design: the SBOM
inventories *what the chart ships*, and image-level scanning/verification already
lives at the image boundary.

## Local reproduction

```bash
# install mikefarah yq (the Python "yq" wrapper won't work here)
# helm + jq are expected too
tools/oci-chart-sbom.sh charts/<C> <release-name> /tmp/<C>.sbom.json
jq . /tmp/<C>.sbom.json
```

## Related

- ADR: [ADR-0132](../adr/0132-sbom-and-cosign-sign-oci-charts.md)
- Delivery model: [continuous-delivery.md](../continuous-delivery.md) (ADR-0055)
- Story/tickets: #136 (story), #161 (this work), #160 (Trivy/Gitleaks gates)
- Org precedent: `lightbridge-code-intelligence/.github/workflows/image-pipeline.yml`
