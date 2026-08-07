#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ARCHIVE="${1:?usage: restore_role_bundle.sh BUNDLE.tar.gz /path/to/flare}"
REPO="${2:?usage: restore_role_bundle.sh BUNDLE.tar.gz /path/to/flare}"
ARCHIVE="$(realpath "$ARCHIVE")"
REPO="$(realpath "$REPO")"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHA_FILE="$ARCHIVE.sha256"

[[ -f "$ARCHIVE" ]] || { echo "[restore-wrapper][ERROR] archive missing" >&2; exit 1; }
[[ -f "$SHA_FILE" ]] || { echo "[restore-wrapper][ERROR] detached SHA missing" >&2; exit 1; }
[[ -d "$REPO" ]] || { echo "[restore-wrapper][ERROR] repo missing" >&2; exit 1; }

python3 -S "$HERE/verify_bundle.py" "$ARCHIVE"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
tar -xzf "$ARCHIVE" -C "$TMP"
ROOT="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d -name 'flare-dependencies-*' -print -quit)"
[[ -n "$ROOT" ]] || { echo "[restore-wrapper][ERROR] bundle root missing" >&2; exit 1; }

"$ROOT/restore.sh" "$REPO"
PROFILE="$(awk -F= '$1=="PROFILE"{print $2}' "$ROOT/profile.env")"
ACTIVATE="$REPO/.flare/profiles/$PROFILE/current/activate.sh"
[[ -f "$ACTIVATE" ]] || { echo "[restore-wrapper][ERROR] activation missing after restore" >&2; exit 1; }

echo "RESTORE WRAPPER PASS: $PROFILE"
echo "Activate with:"
printf 'source %q\n' "$ACTIVATE"
