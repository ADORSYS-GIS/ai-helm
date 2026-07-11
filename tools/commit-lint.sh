#!/usr/bin/env sh
# Conventional-Commits validator — the SINGLE source of truth for commit-message
# structure in this repo. Used by BOTH the local `commit-msg` hook
# (.githooks/commit-msg) and the CI gate (.github/workflows/commit-lint.yml), so
# the rule lives in exactly one place and can't drift.
#
# Full spec + rationale (why the type drives release-please/ADR-0082 version
# bumps, why the PR title is what lands on main): docs/commit-conventions.md.
#
# Usage:
#   tools/commit-lint.sh --file <path>        # validate first line of a message file (hook)
#   tools/commit-lint.sh --message "<line>"   # validate a single subject line (CI: PR title / each commit)
#
# Exit 0 = valid (or intentionally skipped); exit 1 = rejected (prints why).
# POSIX sh: runs under the maintainer's local zsh AND GitHub Actions bash.

set -eu

# ── Allowed types. Keep in sync with docs/commit-conventions.md + release-please-config.json ──
# feat/fix drive releases; the rest are changelog-only or hidden (see the doc).
TYPES='feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert'

# type(optional-scope)(optional !): <description>
#   scope  = lowercase kebab/dotted token (a chart name, `deps`, `adr`, …), optional
#   !      = breaking-change marker, optional
#   ": "   = mandatory separator, then a non-empty description
PATTERN="^(${TYPES})(\([a-z0-9._/-]+\))?!?: .+"

usage() { echo "usage: $0 --file <path> | --message <subject>" >&2; exit 2; }

[ $# -ge 1 ] || usage
mode=$1
case "$mode" in
  --file)    [ $# -eq 2 ] || usage; subject=$(sed -n '/^[^#]/{p;q;}' "$2") ;; # first non-comment line
  --message) [ $# -eq 2 ] || usage; subject=$2 ;;
  *) usage ;;
esac

# ── Skips (not our commits to shape) ──
# Merge commits, git's auto-generated Revert/fixup/squash subjects, and the
# release-please bot title all pass through untouched.
case "$subject" in
  'Merge '*|'Revert "'*|'fixup! '*|'squash! '*|'amend! '*) exit 0 ;;
esac

if printf '%s' "$subject" | grep -Eq "$PATTERN"; then
  # Soft nudge only (never fails): keep subjects tight for readable changelogs.
  len=$(printf '%s' "$subject" | wc -c | tr -d ' ')
  [ "$len" -gt 100 ] && echo "commit-lint: note — subject is ${len} chars (>100); consider tightening." >&2
  exit 0
fi

cat >&2 <<EOF
✖ commit-lint: message is not a valid Conventional Commit.

  offending subject:
    ${subject}

  required shape:
    <type>[optional-scope][!]: <description>

  allowed <type>: feat fix docs style refactor perf test build ci chore revert
  <scope>       : optional, lowercase — a chart name (core-gateway, observability),
                  or deps / adr / release …  e.g. feat(core-gateway): …
  !             : optional breaking-change marker  e.g. feat(mcp)!: …

  examples:
    feat(observability): add rate-limit quota dashboard
    fix(ai-model): spell out invert:false on BackendTrafficPolicy headers
    docs(adr): ADR-0082 — release-please changelog automation
    chore(deps): bump azure/setup-helm to v5
    refactor(core-gateway)!: rename the AuthConfig host key   (breaking)

  why it matters: 'type' decides the release-please version bump (feat→minor,
  fix→patch, ! / BREAKING CHANGE→major) and the CHANGELOG section (ADR-0082).
  full spec: docs/commit-conventions.md
EOF
exit 1
