#!/usr/bin/env bash
#
# migrate-librechat-mongo.sh — copy LibreChat's MongoDB from the OLD cluster
# (Linode) to the NEW cluster (Hetzner) by streaming a mongodump → local archive
# (your backup) → mongorestore. Run on a laptop that has BOTH kubeconfigs.
#
# Why this works with zero local tooling: LibreChat's Mongo is auth-less
# (mongodb://librechat-app-db-0.librechat-app-db-headless:27017, replicaSet rs0)
# and the official `mongo:8.x` image already ships mongodump/mongorestore in the
# pod — so everything runs *inside* the pods; the laptop only pipes bytes and
# keeps a copy.
#
#   PG note: this script is Mongo-only by design. Keycloak/Coder Postgres
#   migration is a separate concern (see docs/2026-linode-to-hetzner-cutover.md).
#
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   OLD_KUBECONFIG=~/.kube/linode ./scripts/migrate-librechat-mongo.sh           # dump + restore
#   ... --dump-only                       # just back up from OLD (no writes to NEW)
#   ... --restore-only ./path/to.archive  # restore a prior archive into NEW
#   ... --dry-run                         # show what it would do, touch nothing
#   ... -y                                # skip the confirmation prompt
#
# Safety: the restore is DESTRUCTIVE on the target (mongorestore --drop replaces
# each restored collection). It NEVER touches the target's admin/config/local.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ─── CONFIG (override via env, or edit here) ─────────────────────────────────
# OLD = source = Linode. Provide a kubeconfig path and/or a context name.
OLD_KUBECONFIG="${OLD_KUBECONFIG:-$HOME/.kube/linode}"
OLD_CONTEXT="${OLD_CONTEXT:-}"
OLD_NS="${OLD_NS:-converse}"
OLD_STS="${OLD_STS:-librechat-app-db}"   # mongo StatefulSet; pod is <sts>-0
OLD_POD="${OLD_POD:-}"                    # set to override pod auto-discovery

# NEW = target = Hetzner.
NEW_KUBECONFIG="${NEW_KUBECONFIG:-/Users/selast/dev/personal/hetzner-k8s/kubeconfig}"
NEW_CONTEXT="${NEW_CONTEXT:-}"
NEW_NS="${NEW_NS:-converse}"
NEW_STS="${NEW_STS:-librechat-app-db}"
NEW_POD="${NEW_POD:-}"

# DBs to migrate. Empty = ALL user dbs (admin/config/local excluded on restore).
# LibreChat defaults to the `test` db (the mongo URI carries no db name), so
# leaving this empty is the safe choice — it captures `test` and/or `LibreChat`.
DB_FILTER="${DB_FILTER:-}"

BACKUP_DIR="${BACKUP_DIR:-./mongo-migration-$(date +%Y%m%d-%H%M%S)}"
# ─────────────────────────────────────────────────────────────────────────────

DRY_RUN=0; DUMP_ONLY=0; RESTORE_FILE=""; ASSUME_YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)      DRY_RUN=1 ;;
    --dump-only)    DUMP_ONLY=1 ;;
    --restore-only) RESTORE_FILE="${2:?--restore-only needs an archive path}"; shift ;;
    -y|--yes)       ASSUME_YES=1 ;;
    -h|--help)      sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

red()  { printf '\033[31m%s\033[0m\n' "$*"; }
grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
ylw()  { printf '\033[33m%s\033[0m\n' "$*"; }
die()  { red "✗ $*"; exit 1; }
run()  { if [ "$DRY_RUN" = 1 ]; then echo "  [dry-run] $*"; else eval "$@"; fi; }

# Build a `kubectl` invocation for OLD / NEW (kubeconfig + optional context).
kold() { kubectl --kubeconfig "$OLD_KUBECONFIG" ${OLD_CONTEXT:+--context "$OLD_CONTEXT"} -n "$OLD_NS" "$@"; }
knew() { kubectl --kubeconfig "$NEW_KUBECONFIG" ${NEW_CONTEXT:+--context "$NEW_CONTEXT"} -n "$NEW_NS" "$@"; }

discover_pod() { # $1=which(old|new)
  if [ "$1" = old ]; then
    [ -n "$OLD_POD" ] && { echo "$OLD_POD"; return; }
    kold get pod "${OLD_STS}-0" -o name >/dev/null 2>&1 && { echo "${OLD_STS}-0"; return; }
    kold get pod -l "app.kubernetes.io/name=mongodb" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null
  else
    [ -n "$NEW_POD" ] && { echo "$NEW_POD"; return; }
    echo "${NEW_STS}-0"
  fi
}

ping_mongo() { # $1=kold|knew  $2=pod
  local fn="$1" pod="$2"
  "$fn" exec "$pod" -- mongosh --quiet --eval 'db.runCommand({ping:1}).ok' 2>/dev/null | tr -d '[:space:]'
}

list_dbs() { # $1=kold|knew $2=pod
  "$1" exec "$2" -- mongosh --quiet --eval \
    'db.adminCommand("listDatabases").databases.map(d=>d.name+" ("+(d.sizeOnDisk/1048576).toFixed(1)+"MB)").join(", ")' 2>/dev/null
}

# ─── Preflight ───────────────────────────────────────────────────────────────
echo "── LibreChat Mongo migration ──────────────────────────────────────────"
echo "OLD: kubeconfig=$OLD_KUBECONFIG ${OLD_CONTEXT:+ctx=$OLD_CONTEXT} ns=$OLD_NS"
echo "NEW: kubeconfig=$NEW_KUBECONFIG ${NEW_CONTEXT:+ctx=$NEW_CONTEXT} ns=$NEW_NS"
echo "DB filter: ${DB_FILTER:-<all user dbs>}"
echo

if [ -n "$RESTORE_FILE" ]; then
  [ -f "$RESTORE_FILE" ] || die "archive not found: $RESTORE_FILE"
  ARCHIVE="$RESTORE_FILE"
else
  command -v kubectl >/dev/null || die "kubectl not on PATH"
  [ -f "$OLD_KUBECONFIG" ] || die "OLD_KUBECONFIG not found: $OLD_KUBECONFIG (set OLD_KUBECONFIG=...)"
  OLD_POD="$(discover_pod old)"; [ -n "$OLD_POD" ] || die "could not find the OLD mongo pod (set OLD_POD=...)"
  echo "OLD pod: $OLD_POD"
  [ "$(ping_mongo kold "$OLD_POD")" = 1 ] || die "OLD mongo did not answer ping"
  grn "OLD mongo reachable. DBs: $(list_dbs kold "$OLD_POD")"
fi

if [ "$DUMP_ONLY" != 1 ]; then
  [ -f "$NEW_KUBECONFIG" ] || die "NEW_KUBECONFIG not found: $NEW_KUBECONFIG"
  NEW_POD="$(discover_pod new)"; [ -n "$NEW_POD" ] || die "could not find the NEW mongo pod (set NEW_POD=...)"
  echo "NEW pod: $NEW_POD"
  [ "$(ping_mongo knew "$NEW_POD")" = 1 ] || die "NEW mongo did not answer ping"
  ylw "NEW mongo reachable. DBs BEFORE restore: $(list_dbs knew "$NEW_POD")"
fi
echo

# ─── Dump (= backup) ─────────────────────────────────────────────────────────
if [ -z "$RESTORE_FILE" ]; then
  mkdir -p "$BACKUP_DIR"
  ARCHIVE="$BACKUP_DIR/librechat-mongo.archive.gz"
  DUMP_ARGS="--archive --gzip"
  [ -n "$DB_FILTER" ] && DUMP_ARGS="$DUMP_ARGS --db=$DB_FILTER"
  echo "Dumping OLD → $ARCHIVE"
  if [ "$DRY_RUN" = 1 ]; then
    echo "  [dry-run] kold exec $OLD_POD -- mongodump $DUMP_ARGS > $ARCHIVE"
  else
    # No -t/TTY — the archive is binary on stdout.
    kold exec "$OLD_POD" -- mongodump $DUMP_ARGS > "$ARCHIVE"
    sz=$(wc -c < "$ARCHIVE" | tr -d ' ')
    [ "$sz" -gt 1024 ] || die "dump looks empty ($sz bytes) — aborting before restore"
    grn "✓ dump complete: $(du -h "$ARCHIVE" | cut -f1) ($sz bytes)"
  fi
fi

[ "$DUMP_ONLY" = 1 ] && { grn "Dump-only done. Archive: $ARCHIVE"; exit 0; }

# ─── Confirm + restore ───────────────────────────────────────────────────────
echo
red "RESTORE is destructive: mongorestore --drop replaces matching collections"
red "on NEW ($NEW_NS/$NEW_POD). admin/config/local are excluded."
if [ "$ASSUME_YES" != 1 ] && [ "$DRY_RUN" != 1 ]; then
  printf "Proceed with restore into NEW? [y/N] "; read -r ans
  [ "$ans" = y ] || [ "$ans" = Y ] || { ylw "Aborted before restore. Archive kept: $ARCHIVE"; exit 0; }
fi

RESTORE_ARGS="--archive --gzip --drop --nsExclude=admin.* --nsExclude=config.* --nsExclude=local.*"
echo "Restoring $ARCHIVE → NEW"
if [ "$DRY_RUN" = 1 ]; then
  echo "  [dry-run] knew exec -i $NEW_POD -- mongorestore $RESTORE_ARGS < $ARCHIVE"
else
  knew exec -i "$NEW_POD" -- mongorestore $RESTORE_ARGS < "$ARCHIVE"
  grn "✓ restore complete"
  grn "NEW DBs AFTER restore: $(list_dbs knew "$NEW_POD")"
fi

echo
grn "Done. Backup archive retained at: $ARCHIVE"
ylw "Next: restart LibreChat so it reconnects cleanly:"
echo "  kubectl --kubeconfig \"$NEW_KUBECONFIG\" -n \"$NEW_NS\" rollout restart deploy/librechat-app"
