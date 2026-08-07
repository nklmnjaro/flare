#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

REPO="${1:-$HOME/Projects/Flare/flare}"
OUT="${2:-$HOME/Projects/Flare/dependency-dist}"
MAX_MIB="${FLARE_ROLE_BUNDLE_MAX_MIB:-300}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$OUT"

for profile in backend frontend qa1 qa2 platform linter; do
  echo
  echo "========== $profile =========="
  "$HERE/accept_bundle.sh" "$profile" "$REPO" "$OUT"

  archive="$(find "$OUT" -maxdepth 1 -type f \
    -name "flare-dependencies-${profile}-linux-*.tar.gz" \
    -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"
  [[ -n "$archive" ]] || {
    echo "[build-all][ERROR] archive not found for $profile" >&2
    exit 1
  }

  bytes="$(stat -c '%s' "$archive")"
  max_bytes="$((MAX_MIB * 1024 * 1024))"
  mib="$(( (bytes + 1024*1024 - 1) / (1024*1024) ))"

  echo "[build-all] $profile bundle size: ${mib} MiB"
  if (( bytes > max_bytes )); then
    echo "[build-all][ERROR] $profile exceeds ${MAX_MIB} MiB safety budget" >&2
    echo "[build-all][ERROR] split the profile instead of distributing it" >&2
    exit 1
  fi
done

echo
echo "ALL ACTIVE ROLE BUNDLES ACCEPTED"
echo "Per-bundle safety budget: ${MAX_MIB} MiB"
echo
find "$OUT" -maxdepth 1 -type f \
  \( -name 'flare-dependencies-backend-*.tar.gz' \
     -o -name 'flare-dependencies-frontend-*.tar.gz' \
     -o -name 'flare-dependencies-qa1-*.tar.gz' \
     -o -name 'flare-dependencies-qa2-*.tar.gz' \
     -o -name 'flare-dependencies-platform-*.tar.gz' \
     -o -name 'flare-dependencies-linter-*.tar.gz' \) \
  -printf '%f  %s bytes\n' | sort
