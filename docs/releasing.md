# Releasing (tag-based deploys)

Deploys are **tag-based**: every self-referencing `targetRevision` in the charts
pins an immutable release tag (e.g. `release-2026.06.08`), and the root
`ai-apps-v2` ArgoCD Application points at that tag. `main` is **never** a deploy
target. See the canonical note in `charts/apps/values.yaml` and the
`targetRevision` section of `CLAUDE.md`.

## TL;DR

```bash
# from a clean tree on the deploy/dev branch:
tools/release.sh                      # cuts release-YYYY.MM.DD (today)
tools/release.sh release-2026.07.01   # or an explicit tag
```

Then do the **one manual step the script can't do for you** — repoint the root:
update your manually-applied `ai-apps-v2` manifest to
`spec.source.targetRevision: <new tag>` and `kubectl apply` it (the script prints
the exact commands; a live `kubectl patch` alone reverts within minutes because
that manifest is the durable source of truth).

## What the script does

`tools/release.sh [TAG] [--dry-run] [--yes] [--repoint] [--no-push]`

1. Reads the **current** tag from `charts/apps/values.yaml` (`selfTargetRevision`).
2. Bumps every self-ref `targetRevision` (the 6 orchestrator/umbrella charts:
   `apps`, `ai-models`, `librechart`, `observability`, `mcps`, `lightbridge`) plus
   the CLAUDE.md canonical note, from the old tag to the new one — **in one commit**.
3. `helm template`-checks every affected chart and asserts the new tag appears in
   the rendered child Applications.
4. Commits, then **tags that commit** and **pushes the tag first** (so nothing
   live ever references a revision that isn't published yet).
5. Pushes the dev branch + `main`.
6. Prints the root-app repoint commands (or runs the live patch with `--repoint`).

**Why bump-and-tag in one commit:** the root renders `charts/apps` *from the tag*,
and that render emits the children's `targetRevision`. So the tagged commit must
already reference its own tag — otherwise children resolve to the *previous*
release. The script guarantees this by tagging the bump commit.

### Flags

| flag | effect |
|---|---|
| `--dry-run` | show the diff that would be committed, then revert; no commit/tag/push. **Always run this first.** |
| `--yes` / `-y` | skip the interactive confirmation. |
| `--no-push` | commit + tag locally only (inspect before pushing). |
| `--repoint` | also `kubectl patch` the live `ai-apps-v2` to the new tag (best-effort — still update the external manifest, see below). |

### Safety

- Refuses to run on a **dirty tree**, on an **existing tag**, or if the new tag
  **equals** the current one.
- An `EXIT` trap reverts the bump if anything fails before the commit, so a failed
  run never leaves the tree half-changed.

## The root-app repoint (manual, durable)

The root `ai-apps-v2` is **applied manually** from a manifest the maintainer holds
outside this repo (field-manager `argocd-controller`). A live `kubectl patch`
reverts within minutes when that manifest re-applies. So the durable repoint is:

```bash
# 1. edit your ai-apps-v2 manifest:  spec.source.targetRevision: <new tag>
kubectl --context admin@homeos -n argocd apply -f <your ai-apps-v2.yaml>
# 2. (optional, immediate) nudge ArgoCD:
kubectl --context admin@homeos -n argocd annotate application ai-apps-v2 \
  argocd.argoproj.io/refresh=hard --overwrite
```

Children pin their own immutable tag, so they stay put even while the root's field
is being updated.

## Rollback

Repoint the root back to a previous tag — it's immutable, so the exact prior state
redeploys:

```bash
kubectl --context admin@homeos -n argocd patch application ai-apps-v2 --type merge \
  -p '{"spec":{"source":{"targetRevision":"release-2026.06.08"}}}'   # and the manifest
```

## Notes

- Tags don't trigger CI (`release-helm-charts` fires on branch push + manual
  dispatch, not on tags), so cutting a deploy tag is side-effect-free.
- Chart-packaging tags (`<chart>-<semver>`, e.g. `apps-1.1.0`) are a separate
  concern from these `release-YYYY.MM.DD` deploy tags.
- Dated docs under `docs/` (audits, cutover logs) intentionally keep their
  historical tag references; the script only rewrites the functional charts +
  the CLAUDE.md canonical note.
