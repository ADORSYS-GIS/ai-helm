Stacked on #1184 (`chore/kubeconform-ci`) — both PRs touch `kubeconform.yaml`, so this one is based on that branch and retargets to `main` when #1184 lands.

## 1. Summary

Pins every rendering workflow to **Helm 3.19.4**, the version the ArgoCD that deploys these charts actually shells out to (v3.4.6 → Helm 3.19.4, `docs/migrations/2026-currency-audit.md:47-50`), instead of 3.15.4.

Five workflows carried the pin, not the two the task named:

- `.github/workflows/helm-lint.yaml:19`
- `.github/workflows/kubeconform.yaml:40`
- `.github/workflows/release-helm-charts.yml:29`
- `.github/workflows/publish-charts-oci.yml:66`
- `.github/workflows/envoy-gateway-lua.yml:44`

The last three declare themselves "aligned with helm-lint.yaml", so bumping only the first two would have swapped one drift for another.

## 2. Intent

The gates must validate the artefact ArgoCD produces. Today they validate a render from a different Helm minor; the class of drift is exactly what `kubeconform` exists to catch.

## 3. Scope

- In scope: the five `azure/setup-helm` version pins, plus the CLAUDE.md note.
- Out of scope: the `values.schema.json` follow-up, and anything that changes chart content.

## 4. Verification

**Render parity measured first** — all 47 charts at `01dd4f3e`, rendered with both binaries (`helm-v3.15.4`, `helm-v3.19.4`), leaves through their `ci/*-values.yaml` fixtures as CI does:

| result | charts |
|---|---|
| byte-identical | 44 |
| ordering/separator-only | `llm-d`, `model-deployment`, `model-serving-qwen3-5` |
| not installable (library) | `common`, `bjw-common` |

For the three that differ, the set of `kind`+`name` resources is identical in both versions — only document ordering and `---` separators move:

```
llm-d             11 resources both sides, same set
model-deployment  11 resources both sides, same set (ConfigMaps reordered)
qwen3-5           11 resources both sides, same set
```

`librechat-search` needed `helm repo add meilisearch https://meilisearch.github.io/meilisearch-kubernetes` before `dep build` — CI already adds it.

Also checked: `helm lint` and `helm template` are unchanged in the two workflows beyond the version string.

## 5. Evidence

The comparison script and outputs are reproducible: `helm template <chart>` per chart per version, `diff -u`. No screenshots.

## 6. Risk Assessment

* [x] Low
* [ ] Medium
* [ ] High

The three differing charts change only resource ordering, which ArgoCD re-sorts by kind anyway. If CI disagrees, this PR is two lines per workflow to revert.

## 7. AI Usage Declaration

AI was used for:

* [x] Understanding existing code
* [x] Generating code
* [ ] Refactoring
* [ ] Generating tests
* [x] Drafting documentation
* [x] Reviewing the diff
* [ ] Not used

Human verification:

* [ ] I understand every meaningful change in this PR
* [ ] I checked generated code manually
* [ ] I checked generated tests manually
* [ ] I removed unsupported AI assumptions
* [ ] I accept responsibility for this PR

> Left unticked on purpose — prepared by cook `opencode-doug`, station `st_1ab1f38788`. No human review has happened.

## 8. Reviewer Focus

* [x] Correctness
* [x] Maintainability
* [ ] Security
* [ ] Performance
* [ ] Tests
* [ ] Product intent
