#!/usr/bin/env bash
# Minimal regression fixture for the confirmed pre-fix ordering defect.
# It intentionally switches current before rejecting an unmanaged project .venv.
set -Eeuo pipefail

REPO="${1:?target repo required}"
PROFILE="${2:?profile required}"
BUNDLE_ID="${3:?bundle id required}"
PROFILE_ROOT="$REPO/.flare/profiles/$PROFILE"
CURRENT="$PROFILE_ROOT/current"

mkdir -p "$PROFILE_ROOT/$BUNDLE_ID"
rm -f "$CURRENT.tmp"
ln -s "$BUNDLE_ID" "$CURRENT.tmp"
mv -Tf "$CURRENT.tmp" "$CURRENT"

if [[ -e "$REPO/.venv" && ! -L "$REPO/.venv" ]]; then
  echo "[legacy-fixture][ERROR] existing .venv is unmanaged; refusing to overwrite" >&2
  exit 1
fi

echo "legacy fixture unexpectedly reached success" >&2
exit 0
