#!/usr/bin/env bash
#
# release.sh — cut a tag-based platform release for ai-helm.
#
# Deploys are TAG-BASED (see CLAUDE.md "targetRevision: TAG-BASED deploys").
# Every self-referencing `targetRevision` in the charts pins an immutable
# release tag; the root `ai-apps-v2` Application points at that tag. This script
# automates the fiddly, order-sensitive bits:
#
#   1. bump every self-ref targetRevision (+ the CLAUDE.md canonical note) to the
#      NEW tag, IN ONE COMMIT,
#   2. render-check every affected chart,
#   3. tag THAT commit and push the tag FIRST (so nothing live ever references a
#      missing revision),
#   4. push the dev branch + main,
#   5. print (or, with --repoint, run) the ArgoCD root-app repoint.
#
# The tag must point at a commit whose charts already reference that tag
# (self-consistency) — that's why the bump and the tag are the same commit.
#
# Usage:
#   tools/release.sh [TAG] [--dry-run] [--yes] [--repoint] [--no-push]
#
#   TAG         release tag to cut (default: release-YYYY.MM.DD, today).
#   --dry-run   show the diff that WOULD be made, then revert; no commit/tag/push.
#   --yes       skip the interactive confirmation.
#   --repoint   also patch the LIVE ai-apps-v2 Application to the new tag
#               (best-effort; the maintainer-held external manifest is the real
#               source of truth — update it too, see the printed reminder).
#   --no-push   commit + tag locally but do not push anything (inspect first).
#
# Safe to re-read: it refuses to run on a dirty tree, on an existing tag, or if
# the new tag equals the current one.
set -euo pipefail

# ── config ────────────────────────────────────────────────────────────────────
CHARTS=(apps ai-models librechart observability mcps lightbridge)
DEV_BRANCH="claude/magical-bohr-390242"
MAIN_BRANCH="main"
ROOT_APP="ai-apps-v2"
ARGO_CTX="admin@homeos"
ARGO_NS="argocd"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── args ──────────────────────────────────────────────────────────────────────
NEW=""; DRYRUN=0; ASSUME_YES=0; REPOINT=0; PUSH=1
for a in "$@"; do
  case "$a" in
    --dry-run) DRYRUN=1 ;;
    --yes|-y)  ASSUME_YES=1 ;;
    --repoint) REPOINT=1 ;;
    --no-push) PUSH=0 ;;
    -*) echo "unknown flag: $a" >&2; exit 2 ;;
    *)  NEW="$a" ;;
  esac
done
NEW="${NEW:-release-$(date +%Y.%m.%d)}"

cd "$REPO_ROOT"
say()  { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }

# ── pre-flight ────────────────────────────────────────────────────────────────
command -v helm >/dev/null || die "helm not found on PATH"
git rev-parse --git-dir >/dev/null 2>&1 || die "not a git repo"

CUR_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[ "$CUR_BRANCH" = "$DEV_BRANCH" ] || warn "on branch '$CUR_BRANCH', expected '$DEV_BRANCH' (continuing)"

# OLD = the tag currently pinned (the YAML key line, not the prose comment)
OLD="$(grep -Em1 '^[[:space:]]*selfTargetRevision:' charts/apps/values.yaml | awk '{print $2}')"
[ -n "$OLD" ] || die "could not read current selfTargetRevision from charts/apps/values.yaml"
[ "$OLD" != "$NEW" ] || die "new tag ($NEW) equals the current one ($OLD) — nothing to do"

# refuse if the tag already exists (local or remote)
if git rev-parse -q --verify "refs/tags/$NEW" >/dev/null; then die "tag $NEW already exists locally"; fi
if git ls-remote --exit-code --tags origin "$NEW" >/dev/null 2>&1; then die "tag $NEW already exists on origin"; fi

# refuse on a dirty tree (the script makes its own bump commit)
if [ "$DRYRUN" -eq 0 ] && [ -n "$(git status --porcelain)" ]; then
  die "working tree is dirty — commit or stash first (this script makes the release-bump commit)"
fi

say "Release: $OLD  →  $NEW   (branch: $CUR_BRANCH)"

# Safety: revert any bump if we exit before committing (dry-run, render failure,
# or user abort) so the tree is never left half-changed.
COMMITTED=0
BUMP_TARGETS=(CLAUDE.md)
for c in "${CHARTS[@]}"; do BUMP_TARGETS+=("charts/$c/values.yaml"); done
revert_changes() { git checkout -- "${BUMP_TARGETS[@]}" 2>/dev/null || true; }
trap '[ "$COMMITTED" = 1 ] || revert_changes' EXIT

# ── 1. bump self-ref targetRevisions + the CLAUDE.md canonical note ────────────
# The release tag string is unique (release-prefixed), so a literal string swap
# is safe and updates value lines + their inline comments together. Dated docs
# under docs/ are point-in-time and intentionally NOT touched.
bump() { # $1 = file
  [ -f "$1" ] || return 0
  sed -i.bak "s|${OLD}|${NEW}|g" "$1" && rm -f "$1.bak"
}
for c in "${CHARTS[@]}"; do bump "charts/$c/values.yaml"; done
bump "CLAUDE.md"

CHANGED="$(git status --porcelain | awk '{print $2}')"
[ -n "$CHANGED" ] || die "no files changed — is $OLD actually present in the charts?"
say "Bumped files:"; echo "$CHANGED" | sed 's/^/    /'

# ── 2. render-check every affected chart ──────────────────────────────────────
say "Render-checking charts…"
for c in "${CHARTS[@]}"; do
  helm template rel "charts/$c" --dry-run >/dev/null 2>/tmp/release-render.err \
    || { cat /tmp/release-render.err >&2; die "helm template failed for charts/$c (run 'helm dep build charts/$c'?)"; }
done
# confirm the new tag actually propagated into rendered child Applications
N="$(helm template rel charts/apps 2>/dev/null | grep -c "targetRevision: ${NEW}" || true)"
say "rendered child Applications pinning ${NEW}: ${N}"
[ "${N:-0}" -ge 1 ] || die "new tag did not appear in the rendered charts/apps output"

# ── dry-run stops here ────────────────────────────────────────────────────────
if [ "$DRYRUN" -eq 1 ]; then
  say "DRY RUN — diff that would be committed:"
  git --no-pager diff --stat
  say "(EXIT trap reverts the bump; nothing committed/tagged/pushed.)"
  exit 0
fi

# ── confirm ───────────────────────────────────────────────────────────────────
if [ "$ASSUME_YES" -eq 0 ]; then
  printf '\nProceed to commit, tag %s, and %s? [y/N] ' "$NEW" "$([ "$PUSH" -eq 1 ] && echo push || echo 'NOT push')"
  read -r ans; case "$ans" in y|Y|yes) ;; *) die "aborted by user (changes reverted)";; esac
fi

# ── 3. commit + tag (the tag points at the bump commit → self-consistent) ─────
git commit -aqm "chore(deploy): release ${NEW}

Tag-based deploy cutover ${OLD} -> ${NEW}. Every self-referencing targetRevision
(charts/{apps,ai-models,librechart,observability,mcps,lightbridge}) pins ${NEW};
the tag points at this commit so children resolve to a tag containing their own
ref. Repoint root ${ROOT_APP} to ${NEW} to ship. main is never a deploy target."
COMMITTED=1   # past this point the bump is committed — the EXIT trap must NOT revert
git tag -a "$NEW" -m "Platform release ${NEW} (from ${OLD})"
say "committed $(git rev-parse --short HEAD) and tagged $NEW"

# ── 4. push: TAG FIRST, then branches ─────────────────────────────────────────
if [ "$PUSH" -eq 1 ]; then
  say "pushing tag $NEW (first, so nothing live references a missing revision)…"
  git push origin "refs/tags/$NEW"
  say "pushing $DEV_BRANCH + $MAIN_BRANCH…"
  git push origin "HEAD:$DEV_BRANCH"
  git push origin "HEAD:$MAIN_BRANCH"
else
  warn "--no-push: tag + commit are LOCAL only. Push the TAG before repointing:"
  echo "    git push origin refs/tags/$NEW && git push origin HEAD:$DEV_BRANCH HEAD:$MAIN_BRANCH"
fi

# ── 5. repoint the root app ───────────────────────────────────────────────────
say "Tag $NEW is published. Final step — repoint the root Application:"
cat <<EOF
  (a) Update your manually-applied ${ROOT_APP} manifest (the durable source of
      truth — a live patch alone reverts within minutes):
          spec.source.targetRevision: ${NEW}
      then:  kubectl --context ${ARGO_CTX} -n ${ARGO_NS} apply -f <your ${ROOT_APP}.yaml>
  (b) (optional, immediate) live patch + refresh:
         kubectl --context ${ARGO_CTX} -n ${ARGO_NS} patch application ${ROOT_APP} --type merge \\
           -p '{"spec":{"source":{"targetRevision":"${NEW}"}}}'
         kubectl --context ${ARGO_CTX} -n ${ARGO_NS} annotate application ${ROOT_APP} \\
           argocd.argoproj.io/refresh=hard --overwrite

  Rollback: repoint ${ROOT_APP} back to ${OLD} (immutable tag → exact prior state).
EOF

if [ "$REPOINT" -eq 1 ]; then
  command -v kubectl >/dev/null || die "--repoint: kubectl not found"
  say "--repoint: patching live ${ROOT_APP} → ${NEW} (remember to update the external manifest!)"
  kubectl --context "$ARGO_CTX" -n "$ARGO_NS" patch application "$ROOT_APP" --type merge \
    -p "{\"spec\":{\"source\":{\"targetRevision\":\"${NEW}\"}}}"
  kubectl --context "$ARGO_CTX" -n "$ARGO_NS" annotate application "$ROOT_APP" \
    argocd.argoproj.io/refresh=hard --overwrite >/dev/null
  warn "live patch applied — it WILL revert unless you also update the external ${ROOT_APP} manifest (step ⓐ)."
fi

say "Done: $NEW"
