#!/usr/bin/env zsh
# Envoy Gateway CONTROL-PLANE gate for every `lua` entry charts/core-gateway renders.
#
# The data-plane harnesses (tests/budget-limiter/, tests/model-policy/) replay the shipped .lua
# through a real Envoy. Neither can see a script Envoy Gateway's CONTROLLER refuses to translate —
# and that refusal is not a skipped filter, it is `directResponse: 500` on EVERY route of the
# Gateway. That is the 2026-09-03 outage (ai-helm-values#367 / #368): `rawget(_G, …)` is nil
# inside EG's gopher-lua validation sandbox, so the whole gateway answered 500 with
# `response_code_details: direct_response` while the proxy logged nothing about Lua.
#
# This runs EG's OWN translator (`egctl x translate`) over the rendered chart. Not a
# re-implementation of the validator — the real thing, at the version prod runs.
#
#   ./tests/envoy-gateway-lua/run.sh          (needs helm, curl, python3 + pyyaml)
#
# No cluster, no Docker, no credentials. Safe to run anywhere, including CI.
set -u

HERE="${0:a:h}"

# KEEP IN LOCKSTEP with the `eg` app pin in charts/apps/values.yaml. A floating "latest" here
# would validate against a translator prod does not run, which is the check that passes cleanly
# and tells you nothing.
EG_VERSION="v1.8.2"

case "$(uname -s)" in
  Darwin) EG_OS="darwin" ;;
  Linux)  EG_OS="linux" ;;
  *)      echo "unsupported OS: $(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in
  arm64|aarch64) EG_ARCH="arm64" ;;
  x86_64|amd64)  EG_ARCH="amd64" ;;
  *)             echo "unsupported arch: $(uname -m)" >&2; exit 1 ;;
esac

BIN_DIR="$HERE/.bin"
EGCTL="$BIN_DIR/egctl-$EG_VERSION"

# sha256 of each platform tarball, pinned alongside EG_VERSION above — this is the ONE place both
# this script and ai-helm-values' render-check read the pin from (ai-helm-values clones this repo
# rather than keeping its own copy of EG_VERSION or these hashes, so the two can never drift).
CHECKSUMS="$HERE/checksums.txt"

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

if [[ ! -x "$EGCTL" ]]; then
  mkdir -p "$BIN_DIR"
  TARBALL="egctl_${EG_VERSION}_${EG_OS}_${EG_ARCH}.tar.gz"
  URL="https://github.com/envoyproxy/gateway/releases/download/${EG_VERSION}/${TARBALL}"
  echo "fetching $TARBALL …"
  TMP=$(mktemp -d) || exit 1
  curl -sSfL -o "$TMP/$TARBALL" "$URL" || { echo "could not download $URL" >&2; exit 1 }

  EXPECTED_SHA=$(awk -v f="$TARBALL" '$2==f{print $1}' "$CHECKSUMS")
  if [[ -z "$EXPECTED_SHA" ]]; then
    echo "no pinned checksum for $TARBALL in $CHECKSUMS — refusing to run an unverified binary" >&2
    exit 1
  fi
  ACTUAL_SHA=$(sha256_of "$TMP/$TARBALL")
  if [[ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]]; then
    echo "checksum mismatch for $TARBALL: expected $EXPECTED_SHA, got $ACTUAL_SHA" >&2
    rm -rf "$TMP"
    exit 1
  fi

  tar xzf "$TMP/$TARBALL" -C "$TMP" || exit 1
  cp "$TMP/bin/$EG_OS/$EG_ARCH/egctl" "$EGCTL" || exit 1
  chmod +x "$EGCTL"
  rm -rf "$TMP"
fi

helm dependency build "$HERE/../../charts/core-gateway" >/dev/null 2>&1

echo "── every rendered EnvoyExtensionPolicy must translate (egctl $EG_VERSION) ─────"
python3 "$HERE/check.py" "$EGCTL"
