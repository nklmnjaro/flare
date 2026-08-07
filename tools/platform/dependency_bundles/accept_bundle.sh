#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

PROFILE="${1:-linter}"
REPO="${2:-$HOME/Projects/Flare/flare}"
OUT="${3:-$HOME/Projects/Flare/dependency-dist}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "$PROFILE" in
  backend|frontend|qa1|qa2|platform|linter) ;;
  *) echo "[accept][ERROR] unknown profile: $PROFILE" >&2; exit 2 ;;
esac

mkdir -p "$OUT"
BUILD_ID="accept-$(date -u +%Y%m%dT%H%M%SZ)-$$"
export FLARE_BUNDLE_BUILD_ID="$BUILD_ID"

"$HERE/flare-bundle.sh" \
  --repo "$REPO" \
  --profile "$PROFILE" \
  --out "$OUT"

ARCHIVE="$(find "$OUT" -maxdepth 1 -type f \
  -name "flare-dependencies-${PROFILE}-linux-*-${BUILD_ID}.tar.gz" \
  -print -quit)"
[[ -n "$ARCHIVE" ]] || {
  echo "[accept][ERROR] built archive not found" >&2
  exit 1
}

python3 "$HERE/verify_bundle.py" "$ARCHIVE"
(
  cd "$OUT"
  sha256sum -c "$(basename "$ARCHIVE").sha256"
)

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
TARGET="$TMP/flare"
mkdir -p "$TARGET"
tar -xzf "$ARCHIVE" -C "$TMP"
BUNDLE_ROOT="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d \
  -name "flare-dependencies-${PROFILE}-*" -print -quit)"
[[ -n "$BUNDLE_ROOT" ]] || {
  echo "[accept][ERROR] extracted bundle root not found" >&2
  exit 1
}

mkdir -p "$TMP/home"
RESTORE_ENV=(env HOME="$TMP/home" PATH=/usr/bin:/bin)
ACTIVATE="$TARGET/.flare/profiles/$PROFILE/current/activate.sh"
CURRENT="$TARGET/.flare/profiles/$PROFILE/current"

echo "[accept] clean restore #1"
"${RESTORE_ENV[@]}" "$BUNDLE_ROOT/restore.sh" "$TARGET"
[[ -L "$CURRENT" ]] || {
  echo "[accept][ERROR] current pointer missing after restore" >&2
  exit 1
}
CURRENT_BEFORE="$(readlink "$CURRENT")"

echo "[accept] idempotent restore #2"
"${RESTORE_ENV[@]}" "$BUNDLE_ROOT/restore.sh" "$TARGET"
[[ "$(readlink "$CURRENT")" == "$CURRENT_BEFORE" ]] || {
  echo "[accept][ERROR] idempotent restore changed bundle id" >&2
  exit 1
}

echo "[accept] isolated activation smoke"
PROFILE="$PROFILE" ACTIVATE="$ACTIVATE" bash --noprofile --norc -c '
  set -e
  before="$-"
  source "$ACTIVATE"
  after="$-"
  [[ "$before" == "$after" ]] || {
    echo "[accept][ERROR] activation changed shell options: $before -> $after" >&2
    exit 1
  }

  case "$PROFILE" in
    qa1|qa2|platform|linter)
      python --version
      ruff --version
      mypy --version
      pytest --version
      ;;
  esac
  case "$PROFILE" in
    linter)
      pylint --version
      pre-commit --version
      hadolint --version
      actionlint --version
      kubeconform -v
      ;;
  esac
  case "$PROFILE" in
    backend|platform)
      go version
      gofmt -h >/dev/null 2>&1 || true
      staticcheck -version
      govulncheck -version
      ;;
  esac
  case "$PROFILE" in
    frontend|platform)
      node --version
      pnpm --version
      ;;
  esac
  case "$PROFILE" in
    backend|qa1|platform)
      buf --version
      protoc --version
      ;;
  esac
  case "$PROFILE" in
    platform)
      kubectl version --client >/dev/null
      helm version --short
      minikube version --short
      hadolint --version
      actionlint --version
      kubeconform -v
      ;;
  esac
'

echo "[accept] intentional RED: broken candidate must preserve previous current"
BROKEN_ROOT="$TMP/broken-${PROFILE}"
cp -a "$BUNDLE_ROOT" "$BROKEN_ROOT"
BROKEN_ID="${BUILD_ID}-intentional-red"
sed -i "s/^BUNDLE_ID=.*/BUNDLE_ID=$BROKEN_ID/" "$BROKEN_ROOT/profile.env"
# Force a post-materialization validation failure without failing integrity.
printf 'command\tpython\tPython 0.0.0-intentional-red\n' >> "$BROKEN_ROOT/postconditions.tsv"
(
  cd "$BROKEN_ROOT"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)
if "${RESTORE_ENV[@]}" "$BROKEN_ROOT/restore.sh" "$TARGET" >/dev/null 2>&1; then
  echo "[accept][ERROR] intentional broken candidate unexpectedly restored" >&2
  exit 1
fi
[[ -L "$CURRENT" && "$(readlink "$CURRENT")" == "$CURRENT_BEFORE" ]] || {
  echo "[accept][ERROR] failed candidate changed previous current" >&2
  exit 1
}
# Previous environment must remain usable.
PROFILE="$PROFILE" ACTIVATE="$ACTIVATE" bash --noprofile --norc -c '
  set -e
  source "$ACTIVATE"
  case "$PROFILE" in
    qa1|qa2|platform|linter) python --version >/dev/null ;;
    backend) go version >/dev/null ;;
    frontend) node --version >/dev/null ;;
  esac
'

echo "[accept] intentional RED: missing supported tool must not produce PASS"
MISSING_ROOT="$TMP/missing-tool-${PROFILE}"
cp -a "$BUNDLE_ROOT" "$MISSING_ROOT"
MISSING_ID="${BUILD_ID}-missing-tool"
sed -i "s/^BUNDLE_ID=.*/BUNDLE_ID=$MISSING_ID/" "$MISSING_ROOT/profile.env"
case "$PROFILE" in
  backend) rm -f "$MISSING_ROOT/payload/bin/staticcheck" ;;
  frontend) rm -f "$MISSING_ROOT/payload/runtime/node/bin/node" ;;
  qa1) rm -f "$MISSING_ROOT/payload/bin/buf" ;;
  qa2) rm -f "$MISSING_ROOT/payload/bin/uv" ;;
  platform) rm -f "$MISSING_ROOT/payload/bin/kubectl" ;;
  linter) rm -f "$MISSING_ROOT/payload/bin/hadolint" ;;
esac
(
  cd "$MISSING_ROOT"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)
if "${RESTORE_ENV[@]}" "$MISSING_ROOT/restore.sh" "$TARGET" >/dev/null 2>&1; then
  echo "[accept][ERROR] bundle missing a supported tool unexpectedly restored" >&2
  exit 1
fi
[[ -L "$CURRENT" && "$(readlink "$CURRENT")" == "$CURRENT_BEFORE" ]] || {
  echo "[accept][ERROR] missing-tool failure changed previous current" >&2
  exit 1
}

echo "[accept] intentional RED: invalid current preflight must not mutate target"
PREFLIGHT="$TMP/preflight"
mkdir -p "$PREFLIGHT/.flare/profiles/$PROFILE"
printf 'do-not-touch\n' > "$PREFLIGHT/.flare/profiles/$PROFILE/current"
BEFORE_PREFLIGHT="$(find "$PREFLIGHT" -type f -o -type l | sort | xargs -r sha256sum 2>/dev/null || true)"
if "${RESTORE_ENV[@]}" "$BUNDLE_ROOT/restore.sh" "$PREFLIGHT" >/dev/null 2>&1; then
  echo "[accept][ERROR] invalid current preflight unexpectedly passed" >&2
  exit 1
fi
AFTER_PREFLIGHT="$(find "$PREFLIGHT" -type f -o -type l | sort | xargs -r sha256sum 2>/dev/null || true)"
[[ "$BEFORE_PREFLIGHT" == "$AFTER_PREFLIGHT" ]] || {
  echo "[accept][ERROR] preflight rejection mutated target" >&2
  exit 1
}

echo "[accept] intentional RED: corrupt checksum must fail before target mutation"
CORRUPT="$TMP/corrupt-${PROFILE}"
cp -a "$BUNDLE_ROOT" "$CORRUPT"
printf '\ncorruption\n' >> "$CORRUPT/profile-toolchain.tsv"
CORRUPT_TARGET="$TMP/corrupt-target"
mkdir -p "$CORRUPT_TARGET"
if "${RESTORE_ENV[@]}" "$CORRUPT/restore.sh" "$CORRUPT_TARGET" >/dev/null 2>&1; then
  echo "[accept][ERROR] corrupted bundle unexpectedly restored" >&2
  exit 1
fi
[[ ! -e "$CORRUPT_TARGET/.flare" ]] || {
  echo "[accept][ERROR] integrity failure mutated target repo" >&2
  exit 1
}

echo "BUNDLE ACCEPTANCE PASS: $PROFILE"
echo "ARTIFACT: $ARCHIVE"
ARCHIVE_SHA="$(sha256sum "$ARCHIVE")"
echo "SHA256: ${ARCHIVE_SHA%% *}"
