# Releasing (tag-based deploys)

Deploys are **tag-based**: every self-referencing `targetRevision` in the charts
pins an immutable release tag (e.g. `release-2026.06.08`), and the root
`ai-apps-v2` ArgoCD Application points at that tag. `main` is **never** a deploy
target. See the canonical note in `charts/apps/values.yaml` and the
`targetRevision` section of `CLAUDE.md`.

## TL;DR

```bash
# from a clean tree on main:
tools/release.sh                      # cuts release-YYYY.MM.DD (today)
tools/release.sh release-2026.07.01   # or an explicit tag
```

Then do the **one manual step the script can't do for you** — repoint the root:
bump the `ai-apps-v2` entry's `targetRevision` to `<new tag>` in **home-os**
`charts/cd/values.yaml` and push home-os `main`. ArgoCD's `cd` app (selfHeal)
reconciles it and the root rolls forward. ⚠️ Skip this and the root self-heals
back to the previous tag — an effective rollback. (A live `kubectl patch` alone
reverts within minutes because home-os `charts/cd` is the durable source.)

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
5. Pushes `main`.
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
| `--repoint` | also `kubectl patch` the live `ai-apps-v2` to the new tag (immediate stop-gap — still bump home-os `charts/cd`, see below). |

### Safety

- Refuses to run on a **dirty tree**, on an **existing tag**, or if the new tag
  **equals** the current one.
- An `EXIT` trap reverts the bump if anything fails before the commit, so a failed
  run never leaves the tree half-changed.

## The root-app repoint (durable, in home-os)

The root `ai-apps-v2` Application is **GitOps-managed in `home-os`** — its
`targetRevision` lives in `home-os` `charts/cd/values.yaml` (the `ai-apps-v2`
entry), reconciled by ArgoCD's `cd` app (`selfHeal: true`). It is NOT applied by
hand, so a live `kubectl patch` reverts within minutes when `cd` re-syncs. The
durable repoint is therefore a home-os commit:

```bash
# 1. in home-os charts/cd/values.yaml, bump the ai-apps-v2 entry:
#       targetRevision: <new tag>
git -C <home-os> commit -am 'chore(cd): repoint ai-apps-v2 → <new tag>'
git -C <home-os> push           # ArgoCD's cd app rolls the root forward
# 2. (optional, immediate) nudge ArgoCD so it doesn't wait for the next poll:
kubectl --context admin@homeos -n argocd annotate application ai-apps-v2 \
  argocd.argoproj.io/refresh=hard --overwrite
```

Children pin their own immutable tag, so they stay put even while the root's field
is being updated.

## Rollback

Repoint the root back to a previous tag — it's immutable, so the exact prior state
redeploys. Set `targetRevision` back in home-os `charts/cd/values.yaml` and push
(that's the durable revert); for immediate effect, also live-patch:

```bash
kubectl --context admin@homeos -n argocd patch application ai-apps-v2 --type merge \
  -p '{"spec":{"source":{"targetRevision":"release-2026.06.08-v09"}}}'   # then revert it in home-os charts/cd too
```

## External (first-party) app sources are pinned to commits, not HEAD

A reproducible release also requires that apps sourced from **other** ADORSYS-GIS
repos don't track HEAD. These are pinned to commit SHAs in `charts/apps/values.yaml`
(they do NOT ride the ai-helm release tag — they're different repos):

| app(s) | repo | how to bump |
|---|---|---|
| `opencode-k8s-agent`, `apprise-api` | `opencode-k8s-agent.git` | edit the SHA |
| `converse-ui` | `converse-frontends` | edit the SHA |

To take a newer version: `git ls-remote https://github.com/ADORSYS-GIS/<repo> HEAD`,
put the SHA in `charts/apps/values.yaml`, then cut a release. **`tools/release.sh`
does NOT touch these** — it only bumps the ai-helm self-ref tag; external SHAs are
a deliberate manual bump. (Upstream Helm charts — `aieg`, `eg`, `external-secrets`,
… — are already version-pinned and need no action.)

## Notes

- Tags don't trigger CI (`release-helm-charts` fires on branch push + manual
  dispatch, not on tags), so cutting a deploy tag is side-effect-free.
- Chart-packaging tags (`<chart>-<semver>`, e.g. `apps-1.1.0`) are a separate
  concern from these `release-YYYY.MM.DD` deploy tags.
- Dated docs under `docs/` (audits, cutover logs) intentionally keep their
  historical tag references; the script only rewrites the functional charts +
  the CLAUDE.md canonical note.
