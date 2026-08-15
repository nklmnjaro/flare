#!/usr/bin/bash
set -Eeuo pipefail
IFS=$'\n\t'
PATH=/usr/bin:/bin
export PATH

ARCHIVE="${1:?usage: restore_role_bundle.sh BUNDLE.tar.gz /path/to/flare}"
REPO="${2:?usage: restore_role_bundle.sh BUNDLE.tar.gz /path/to/flare}"
REPO="$(realpath "$REPO")"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_PYTHON="${FLARE_BUNDLE_PYTHON:-}"
[[ -d "$REPO" ]] || { echo "[restore-wrapper][ERROR] repo missing" >&2; exit 1; }
[[ -n "$BUNDLE_PYTHON" ]] || {
  echo "[restore-wrapper][ERROR] set FLARE_BUNDLE_PYTHON to an explicitly trusted interpreter" >&2
  exit 1
}
[[ -x "$BUNDLE_PYTHON" ]] || {
  echo "[restore-wrapper][ERROR] pinned bundle verifier Python is missing" >&2
  exit 1
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
"$BUNDLE_PYTHON" -I -B -S "$HERE/verify_bundle.py" \
  --extract-to "$TMP" "$ARCHIVE"
ROOT="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d -name 'flare-dependencies-*' -print -quit)"
[[ -n "$ROOT" ]] || { echo "[restore-wrapper][ERROR] bundle root missing" >&2; exit 1; }

"$ROOT/restore.sh" "$REPO"
PROFILE="$(awk -F= '$1=="PROFILE"{print $2}' "$ROOT/profile.env")"
ACTIVATE="$REPO/.flare/profiles/$PROFILE/current/activate.sh"
[[ -f "$ACTIVATE" ]] || { echo "[restore-wrapper][ERROR] activation missing after restore" >&2; exit 1; }

echo "RESTORE WRAPPER PASS: $PROFILE"
echo "Activate with:"
printf 'source %q\n' "$ACTIVATE"
