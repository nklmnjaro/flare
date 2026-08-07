#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

REPO="${HOME}/Projects/Flare/flare"
PROFILE="linter"
OUT=""
BUILD_ID="${FLARE_BUNDLE_BUILD_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"

log()  { printf '[flare-bundle] %s\n' "$*"; }
warn() { printf '[flare-bundle][WARN] %s\n' "$*" >&2; }
die()  { printf '[flare-bundle][ERROR] %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Flare dependency bundle builder v3 canonical

Usage:
  ./flare-bundle.sh --profile PROFILE [--repo PATH] [--out PATH]

Profiles:
  backend frontend qa1 qa2 platform linter

The builder consumes an already installed project-local toolchain under
<repo>/.flare and emits a portable bundle with:
- one deterministic top-level directory;
- normalized tar ownership;
- profile-specific manifest;
- internal payload SHA256SUMS that does not hash itself;
- non-destructive candidate restore;
- offline uv sync with --frozen;
- postcondition/version checks;
- internal integrity preflight before target mutation.
EOF
}

while (($#)); do
  case "$1" in
    --repo) REPO="${2:?missing repo}"; shift 2 ;;
    --profile) PROFILE="${2:?missing profile}"; shift 2 ;;
    --out) OUT="${2:?missing out}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

case "$PROFILE" in
  backend|frontend|qa1|qa2|platform|linter) ;;
  *) die "unknown profile: $PROFILE" ;;
esac

REPO="$(cd "$REPO" && pwd)"
FLARE="$REPO/.flare"
BIN="$FLARE/bin"
RUNTIME="$FLARE/runtime"
CACHE="$FLARE/cache"
BOOTSTRAP_PY="$FLARE/bootstrap-python"
GLOBAL_MANIFEST="$FLARE/toolchain.lock.tsv"

[[ -d "$FLARE" ]] || die "missing toolchain: $FLARE"
[[ -f "$GLOBAL_MANIFEST" ]] || die "missing global toolchain manifest: $GLOBAL_MANIFEST"

OUT="${OUT:-$REPO/../dependency-dist}"
mkdir -p "$OUT"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$(uname -m)" in
  x86_64|amd64) ARCH="amd64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  *) die "unsupported architecture: $(uname -m)" ;;
esac
[[ "$OS" == "linux" ]] || die "only Linux bundles are supported"

need_python()    { [[ "$PROFILE" =~ ^(qa1|qa2|linter)$ ]]; }
need_go()        { [[ "$PROFILE" == "backend" ]]; }
need_node()      { [[ "$PROFILE" == "frontend" ]]; }
need_contracts() { [[ "$PROFILE" =~ ^(backend|qa1)$ ]]; }
need_browser()   { return 1; }

profile_tools() {
  case "$PROFILE" in
    backend)  printf '%s\n' go gofmt goimports staticcheck golangci-lint govulncheck dlv protoc-gen-go buf protoc ;;
    frontend) printf '%s\n' node pnpm ;;
    qa1)      printf '%s\n' uv python buf protoc ;;
    qa2)      printf '%s\n' uv python ;;
    platform) printf '%s\n' kubectl helm minikube ;;
    linter)   printf '%s\n' uv python hadolint actionlint kubeconform ;;
  esac
}

assert_source_ready() {
  local missing=0 tool
  while read -r tool; do
    [[ -z "$tool" ]] && continue
    case "$tool" in
      python)
        [[ -d "$RUNTIME/python" ]] || { warn "missing runtime/python"; missing=1; }
        ;;
      go)
        [[ -x "$RUNTIME/go/bin/go" ]] || { warn "missing runtime/go/bin/go"; missing=1; }
        ;;
      gofmt)
        [[ -x "$RUNTIME/go/bin/gofmt" ]] || { warn "missing runtime/go/bin/gofmt"; missing=1; }
        ;;
      node)
        [[ -x "$RUNTIME/node/bin/node" ]] || { warn "missing runtime/node/bin/node"; missing=1; }
        ;;
      pnpm)
        [[ -e "$RUNTIME/pnpm/bin/pnpm" || -x "$BIN/pnpm" ]] || { warn "missing pnpm"; missing=1; }
        ;;
      *)
        [[ -e "$BIN/$tool" || -L "$BIN/$tool" ]] || {
          warn "missing required source tool: $tool"
          missing=1
        }
        ;;
    esac
  done < <(profile_tools)

  if need_python; then
    [[ -x "$BIN/uv" ]] || { warn "missing uv"; missing=1; }
    [[ -f "$BOOTSTRAP_PY/pyproject.toml" ]] || { warn "missing bootstrap Python project"; missing=1; }
    [[ -f "$BOOTSTRAP_PY/uv.lock" ]] || { warn "missing bootstrap Python uv.lock"; missing=1; }
    [[ -d "$CACHE/uv" ]] || { warn "missing uv cache"; missing=1; }
  fi

  ((missing == 0)) || die "source toolchain is incomplete for profile $PROFILE"
}

copy_deref() {
  local src="$1" dst="$2"
  [[ -e "$src" || -L "$src" ]] || return 0
  mkdir -p "$(dirname "$dst")"
  cp -aL "$src" "$dst"
}

copy_preserve() {
  local src="$1" dst="$2"
  [[ -e "$src" || -L "$src" ]] || return 0
  mkdir -p "$(dirname "$dst")"
  cp -a "$src" "$dst"
}

safe_symlinks() {
  local root="$1" link target resolved
  while IFS= read -r -d '' link; do
    target="$(readlink "$link")"
    [[ "$target" != /* ]] || die "absolute symlink in bundle: $link -> $target"
    resolved="$(realpath -m "$(dirname "$link")/$target")"
    case "$resolved" in
      "$root"/*) ;;
      *) die "escaping symlink in bundle: $link -> $target" ;;
    esac
  done < <(find "$root" -type l -print0)
}

write_profile_manifest() {
  local dest="$1"
  printf '# tool\tversion\tsource\tsha256\tkind\tbundled\tprofile\n' > "$dest"
  local tool line
  while read -r tool; do
    [[ -z "$tool" ]] && continue
    line="$(awk -F '\t' -v n="$tool" 'NR>1 && $1==n {print; exit}' "$GLOBAL_MANIFEST")"
    if [[ -n "$line" ]]; then
      printf '%s\ttrue\t%s\n' "$line" "$PROFILE" >> "$dest"
      continue
    fi
    if [[ "$tool" == "gofmt" ]]; then
      line="$(awk -F '\t' 'NR>1 && $1=="go" {
        OFS="\t"; $1="gofmt"; $5="runtime-companion"; print; exit
      }' "$GLOBAL_MANIFEST")"
      [[ -n "$line" ]] || die "profile tool missing from global manifest: go/gofmt"
      printf '%s\ttrue\t%s\n' "$line" "$PROFILE" >> "$dest"
      continue
    fi
    die "profile tool missing from global manifest: $tool"
  done < <(profile_tools)
}

capture_postconditions() {
  local dest="$1"
  printf '# kind\tname\texpected\n' > "$dest"

  if need_python; then
    printf 'command\tpython\t%s\n' "$("$SOURCE_VENV/bin/python" --version 2>&1)" >> "$dest"
    local cli
    for cli in pytest ruff mypy; do
      [[ -x "$SOURCE_VENV/bin/$cli" ]] || die "source venv missing required CLI: $cli"
      printf 'command\t%s\t%s\n' "$cli" "$("$SOURCE_VENV/bin/$cli" --version 2>&1 | head -1)" >> "$dest"
    done
    if [[ "$PROFILE" == "linter" ]]; then
      for cli in pylint pre-commit; do
        [[ -x "$SOURCE_VENV/bin/$cli" ]] || die "source venv missing quality CLI: $cli"
        printf 'command\t%s\t%s\n' "$cli" "$("$SOURCE_VENV/bin/$cli" --version 2>&1 | head -1)" >> "$dest"
      done
    fi
    if [[ "$PROFILE" == "qa1" ]]; then
      printf 'python-import\tqa1\tboto3,httpx,psycopg,pytest\n' >> "$dest"
    fi
  fi

  local b
  while read -r b; do
    [[ -z "$b" ]] && continue
    case "$b" in
      python|uv) continue ;;
      go)
        [[ -x "$RUNTIME/go/bin/go" ]] && printf 'command\tgo\t%s\n' "$("$RUNTIME/go/bin/go" version 2>&1)" >> "$dest"
        ;;
      node)
        [[ -x "$RUNTIME/node/bin/node" ]] && printf 'command\tnode\t%s\n' "$("$RUNTIME/node/bin/node" --version 2>&1)" >> "$dest"
        ;;
      pnpm)
        local pn="$BIN/pnpm"
        if [[ -x "$pn" || -L "$pn" ]]; then
          local pnpm_version
          pnpm_version="$(PATH="$RUNTIME/node/bin:$BIN:/usr/bin:/bin" "$pn" --version 2>&1 | head -1)" || \
            die "cannot execute source pnpm with bundled Node"
          [[ -n "$pnpm_version" ]] || die "source pnpm returned empty version"
          printf 'command\tpnpm\t%s\n' "$pnpm_version" >> "$dest"
        fi
        ;;
      *)
        [[ -x "$BIN/$b" || -L "$BIN/$b" ]] || continue
        ;;
    esac
  done < <(profile_tools)
}

NAME="flare-dependencies-${PROFILE}-${OS}-${ARCH}-${BUILD_ID}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
ROOT="$WORK/$NAME"
SOURCE_VENV=""

assert_source_ready

prepare_source_python_env() {
  need_python || return 0
  SOURCE_VENV="$WORK/source-python-$PROFILE"
  export UV_PYTHON_INSTALL_DIR="$RUNTIME/python"
  export UV_CACHE_DIR="$CACHE/uv"
  UV_GROUP_ARGS=(--group quality)
  if [[ "$PROFILE" == "qa1" ]]; then
    UV_GROUP_ARGS+=(--group qa1)
  fi
  if [[ "$PROFILE" == "qa2" ]]; then
    UV_GROUP_ARGS+=(--group qa2)
  fi
  UV_PROJECT_ENVIRONMENT="$SOURCE_VENV" \
    "$BIN/uv" sync \
      --project "$BOOTSTRAP_PY" \
      --frozen \
      --offline \
      "${UV_GROUP_ARGS[@]}"
  [[ -x "$SOURCE_VENV/bin/python" ]] || die "source Python environment was not created"
}

prepare_source_python_env
PAYLOAD="$ROOT/payload"
mkdir -p "$PAYLOAD/bin" "$PAYLOAD/runtime" "$PAYLOAD/cache"

# Runtime/tool copying. Python runtime is dereferenced deliberately to eliminate
# uv-managed absolute alias symlinks from the portable artifact.
if need_python; then
  copy_deref "$BIN/uv" "$PAYLOAD/bin/uv"
  copy_deref "$BIN/uvx" "$PAYLOAD/bin/uvx"
  copy_deref "$RUNTIME/python" "$PAYLOAD/runtime/python"
  copy_preserve "$CACHE/uv" "$PAYLOAD/cache/uv"
  copy_preserve "$BOOTSTRAP_PY" "$PAYLOAD/bootstrap-python"
fi

if need_go; then
  copy_preserve "$RUNTIME/go" "$PAYLOAD/runtime/go"
  for b in goimports staticcheck golangci-lint govulncheck dlv protoc-gen-go; do
    copy_deref "$BIN/$b" "$PAYLOAD/bin/$b"
  done
fi

if need_node; then
  copy_preserve "$RUNTIME/node" "$PAYLOAD/runtime/node"
  copy_preserve "$RUNTIME/pnpm" "$PAYLOAD/runtime/pnpm"
fi

if need_contracts; then
  copy_deref "$BIN/buf" "$PAYLOAD/bin/buf"
  copy_deref "$BIN/protoc" "$PAYLOAD/bin/protoc"
  copy_preserve "$FLARE/include" "$PAYLOAD/include"
fi

if [[ "$PROFILE" == "platform" ]]; then
  for b in kubectl helm minikube; do
    copy_deref "$BIN/$b" "$PAYLOAD/bin/$b"
  done
fi

if [[ "$PROFILE" == "linter" ]]; then
  for b in hadolint actionlint kubeconform; do
    copy_deref "$BIN/$b" "$PAYLOAD/bin/$b"
  done
fi


write_profile_manifest "$ROOT/profile-toolchain.tsv"
capture_postconditions "$ROOT/postconditions.tsv"

cat > "$ROOT/profile.env" <<EOF
PROFILE=$PROFILE
BUNDLE_ID=$BUILD_ID
OS=$OS
ARCH=$ARCH
EOF

cat > "$ROOT/restore.sh" <<'RESTORE'
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="$(awk -F= '$1=="PROFILE"{print $2}' "$ROOT/profile.env")"
BUNDLE_ID="$(awk -F= '$1=="BUNDLE_ID"{print $2}' "$ROOT/profile.env")"
REPO="${1:-$HOME/Projects/Flare/flare}"

log()  { printf '[flare-restore] %s\n' "$*"; }
die()  { printf '[flare-restore][ERROR] %s\n' "$*" >&2; exit 1; }

case "$PROFILE" in
  backend|frontend|qa1|qa2|platform|linter) ;;
  *) die "unsupported profile: $PROFILE" ;;
esac
[[ "$BUNDLE_ID" =~ ^[A-Za-z0-9._-]+$ ]] || die "unsafe bundle id: $BUNDLE_ID"
[[ -d "$REPO" ]] || die "target repo does not exist: $REPO"
REPO="$(cd "$REPO" && pwd)"

# Phase A: bundle-only integrity/safety preflight. No target mutation.
(
  cd "$ROOT"
  sha256sum -c SHA256SUMS
) >/dev/null || die "bundle integrity check failed"

while IFS= read -r -d '' link; do
  target="$(readlink "$link")"
  [[ "$target" != /* ]] || die "absolute symlink in bundle payload: $link"
  resolved="$(realpath -m "$(dirname "$link")/$target")"
  case "$resolved" in
    "$ROOT"/*) ;;
    *) die "escaping symlink in bundle payload: $link -> $target" ;;
  esac
done < <(find "$ROOT/payload" -type l -print0)

FLARE="$REPO/.flare"
PROFILES="$FLARE/profiles"
PROFILE_ROOT="$PROFILES/$PROFILE"
FINAL_STATE="$PROFILE_ROOT/$BUNDLE_ID"
CURRENT="$PROFILE_ROOT/current"
INCOMPLETE_MARKER=".flare-incomplete"
MANAGED_MARKER=".flare-managed-profile"

profile_needs_python() {
  [[ "$PROFILE" =~ ^(qa1|qa2|linter)$ ]]
}

# Phase B: classify target state before any managed-state mutation.
target_preflight() {
  if [[ -e "$CURRENT" || -L "$CURRENT" ]]; then
    [[ -L "$CURRENT" ]] || die "current profile pointer is not a symlink: $CURRENT"
    old_target="$(readlink "$CURRENT")"
    [[ "$old_target" =~ ^[A-Za-z0-9._-]+$ ]] || die "unsafe current profile pointer: $old_target"
    old_resolved="$(realpath -m "$PROFILE_ROOT/$old_target")"
    case "$old_resolved" in
      "$PROFILE_ROOT"/*) ;;
      *) die "current profile pointer escapes profile root: $old_target" ;;
    esac
    [[ -d "$old_resolved" ]] || die "current profile pointer is broken: $old_target"
    [[ ! -e "$old_resolved/$INCOMPLETE_MARKER" ]] || die "current profile points to incomplete state: $old_target"
  fi
}

target_preflight

detect_tool_version() {
  local state="$1" name="$2"
  local bin="$state/bin" venv="$state/venv"
  local value=""

  case "$name" in
    uv)
      value="$("$bin/uv" --version 2>&1 | awk 'NR==1 {print $2}')"
      ;;
    python)
      value="$("$venv/bin/python" -c 'import platform; print(platform.python_version())')"
      ;;
    go|gofmt)
      value="$("$bin/go" version 2>&1 | awk '{
        for (i=1; i<=NF; i++) if ($i ~ /^go[0-9]/) {sub(/^go/, "", $i); print $i; exit}
      }')"
      ;;
    goimports|staticcheck|govulncheck|dlv|protoc-gen-go)
      value="$("$bin/go" version -m "$bin/$name" 2>/dev/null | \
        awk '$1=="mod" {print $3; exit}')"
      ;;
    golangci-lint)
      value="$("$bin/golangci-lint" version 2>&1 | \
        sed -nE '1{s/.*version[[:space:]]+v?([^[:space:]]+).*/\1/p;q}')"
      ;;
    buf)
      value="$("$bin/buf" --version 2>&1 | head -1)"
      ;;
    protoc)
      value="$("$bin/protoc" --version 2>&1 | awk 'NR==1 {print $NF}')"
      ;;
    node)
      value="$("$bin/node" --version 2>&1 | sed -nE '1{s/^v//;p;q}')"
      ;;
    pnpm)
      value="$(PATH="$bin:/usr/bin:/bin" "$bin/pnpm" --version 2>&1 | head -1)"
      ;;
    kubectl)
      value="$("$bin/kubectl" version --client -o json 2>/dev/null | \
        tr -d '\n ' | sed -nE 's/.*"gitVersion":"v([^"]+)".*/\1/p')"
      ;;
    helm)
      value="$("$bin/helm" version --short 2>&1 | \
        sed -nE '1{s/^v//;s/\+.*$//;p;q}')"
      ;;
    minikube)
      value="$("$bin/minikube" version --short 2>&1 | \
        sed -nE '1{s/^v//;p;q}')"
      ;;
    hadolint)
      value="$("$bin/hadolint" --version 2>&1 | awk 'NR==1 {print $NF}')"
      ;;
    actionlint)
      value="$("$bin/actionlint" --version 2>&1 | head -1)"
      ;;
    kubeconform)
      value="$("$bin/kubeconform" -v 2>&1 | sed -nE '1{s/^v//;p;q}')"
      ;;
    *)
      die "no version probe for supported tool: $name"
      ;;
  esac

  [[ -n "$value" ]] || die "empty version probe for supported tool: $name"
  printf '%s\n' "$value"
}

validate_profile_versions() {
  local state="$1"
  local tool expected source sha kind bundled profile actual
  while IFS=$'\t' read -r tool expected source sha kind bundled profile; do
    [[ -z "$tool" || "$tool" == \#* ]] && continue
    [[ -n "$expected" && "$expected" != "unknown" && "$expected" != "-" ]] || \
      die "supported tool has no declared version: $tool"
    actual="$(detect_tool_version "$state" "$tool")"
    [[ "$actual" == "$expected" ]] || \
      die "$tool version mismatch: expected '$expected', got '$actual'"
  done < "$state/profile-toolchain.tsv"
}

verify_postconditions() {
  local state="$1"
  local venv="$state/venv"
  local bin="$state/bin"
  local kind name expected actual
  while IFS=$'\t' read -r kind name expected; do
    [[ -z "$kind" || "$kind" == \#* ]] && continue
    case "$kind" in
      command)
        case "$name" in
          python)
            [[ -x "$venv/bin/python" ]] || die "missing restored Python"
            actual="$("$venv/bin/python" --version 2>&1)"
            ;;
          pytest|ruff|mypy|pylint|pre-commit|playwright)
            [[ -x "$venv/bin/$name" ]] || die "missing restored CLI: $name"
            actual="$("$venv/bin/$name" --version 2>&1 | head -1)"
            ;;
          go)
            [[ -x "$bin/go" ]] || die "missing restored Go"
            actual="$("$bin/go" version 2>&1)"
            ;;
          node)
            [[ -x "$bin/node" ]] || die "missing restored Node"
            actual="$("$bin/node" --version 2>&1)"
            ;;
          pnpm)
            [[ -x "$bin/pnpm" ]] || die "missing restored pnpm"
            actual="$(PATH="$bin:/usr/bin:/bin" "$bin/pnpm" --version 2>&1 | head -1)"
            ;;
          *) continue ;;
        esac
        [[ "$actual" == "$expected" ]] || \
          die "$name version mismatch: expected '$expected', got '$actual'"
        ;;
      python-import)
        local imports="" module
        IFS=',' read -r -a modules <<<"$expected"
        for module in "${modules[@]}"; do imports+="import ${module};"; done
        "$venv/bin/python" -c "$imports" || \
          die "Python import postcondition failed: $expected"
        ;;
    esac
  done < "$state/postconditions.tsv"
}

validate_profile_manifest() {
  local state="$1"
  local tool version source sha kind bundled profile
  while IFS=$'\t' read -r tool version source sha kind bundled profile; do
    [[ -z "$tool" || "$tool" == \#* ]] && continue
    [[ "$bundled" == "true" ]] || die "profile manifest marks $tool as not bundled"
    [[ "$profile" == "$PROFILE" ]] || die "profile manifest mismatch for $tool"
    case "$tool" in
      python) [[ -d "$state/runtime/python" ]] || die "manifest tool missing: python runtime" ;;
      go) [[ -x "$state/runtime/go/bin/go" ]] || die "manifest tool missing: go" ;;
      gofmt) [[ -x "$state/runtime/go/bin/gofmt" ]] || die "manifest tool missing: gofmt" ;;
      node) [[ -x "$state/runtime/node/bin/node" ]] || die "manifest tool missing: node" ;;
      pnpm) [[ -e "$state/runtime/pnpm/bin/pnpm" || -x "$state/bin/pnpm" ]] || die "manifest tool missing: pnpm" ;;
      uv) [[ -x "$state/bin/uv" ]] || die "manifest tool missing: uv" ;;
      *) [[ -e "$state/bin/$tool" || -L "$state/bin/$tool" ]] || die "manifest tool missing: $tool" ;;
    esac
  done < "$state/profile-toolchain.tsv"
}

write_state_activation() {
  local state="$1"
  cat > "$state/activate.sh" <<'ACT'
#!/usr/bin/env bash
# Flare managed profile activation. Sourced file: never mutate caller shell options/traps.
_STATE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)" || return 1
_PROFILE="PROFILE_PLACEHOLDER"
_VENV="$_STATE/venv"

if [[ ! -f "$_STATE/profile-toolchain.tsv" || ! -f "$_STATE/postconditions.tsv" ]]; then
  echo "[flare][ERROR] restored profile contract is incomplete: $_PROFILE" >&2
  unset _STATE _PROFILE _VENV
  return 1
fi

while IFS=$'\t' read -r _TOOL _VERSION _SOURCE _SHA _KIND _BUNDLED _MANIFEST_PROFILE; do
  [[ -z "$_TOOL" || "$_TOOL" == \#* ]] && continue
  if [[ "$_BUNDLED" != "true" || "$_MANIFEST_PROFILE" != "$_PROFILE" ]]; then
    echo "[flare][ERROR] invalid supported-tool manifest entry: $_TOOL" >&2
    unset _STATE _PROFILE _VENV _TOOL _VERSION _SOURCE _SHA _KIND _BUNDLED _MANIFEST_PROFILE
    return 1
  fi
  if [[ "$_TOOL" == "python" ]]; then
    _TOOL_PATH="$_VENV/bin/python"
  else
    _TOOL_PATH="$_STATE/bin/$_TOOL"
  fi
  if [[ ! -x "$_TOOL_PATH" ]]; then
    echo "[flare][ERROR] supported tool is missing: $_TOOL" >&2
    unset _STATE _PROFILE _VENV _TOOL _VERSION _SOURCE _SHA _KIND _BUNDLED _MANIFEST_PROFILE _TOOL_PATH
    return 1
  fi
done < "$_STATE/profile-toolchain.tsv"

while IFS=$'\t' read -r _POST_KIND _POST_NAME _POST_EXPECTED; do
  [[ -z "$_POST_KIND" || "$_POST_KIND" == \#* || "$_POST_KIND" != "command" ]] && continue
  case "$_POST_NAME" in
    python|pytest|ruff|mypy|pylint|pre-commit|playwright)
      _POST_PATH="$_VENV/bin/$_POST_NAME"
      ;;
    *)
      _POST_PATH="$_STATE/bin/$_POST_NAME"
      ;;
  esac
  if [[ ! -x "$_POST_PATH" ]]; then
    echo "[flare][ERROR] required command is missing: $_POST_NAME" >&2
    unset _STATE _PROFILE _VENV _POST_KIND _POST_NAME _POST_EXPECTED _POST_PATH
    return 1
  fi
done < "$_STATE/postconditions.tsv"

if [[ "$_PROFILE" =~ ^(qa1|qa2|linter)$ ]]; then
  export VIRTUAL_ENV="$_VENV"
  export PATH="$_VENV/bin:$_STATE/bin:$PATH"
else
  unset VIRTUAL_ENV 2>/dev/null || true
  export PATH="$_STATE/bin:$PATH"
fi
export FLARE_REPO_ROOT="REPO_PLACEHOLDER"
export PLAYWRIGHT_BROWSERS_PATH="$_STATE/playwright"
echo "[flare] activated profile: $_PROFILE"
unset _STATE _PROFILE _VENV _TOOL _VERSION _SOURCE _SHA _KIND _BUNDLED \
  _MANIFEST_PROFILE _TOOL_PATH _POST_KIND _POST_NAME _POST_EXPECTED _POST_PATH
return 0
ACT
  sed -i "s/PROFILE_PLACEHOLDER/$PROFILE/g" "$state/activate.sh"
  escaped_repo="${REPO//\\/\\\\}"
  escaped_repo="${escaped_repo//&/\\&}"
  escaped_repo="${escaped_repo//|/\\|}"
  sed -i "s|REPO_PLACEHOLDER|$escaped_repo|g" "$state/activate.sh"
  chmod +x "$state/activate.sh"
}

prepare_runtime_links() {
  local state="$1"
  local bin="$state/bin"
  local runtime="$state/runtime"
  mkdir -p "$bin"
  if [[ -x "$runtime/go/bin/go" ]]; then
    ln -sf ../runtime/go/bin/go "$bin/go"
  fi
  if [[ -x "$runtime/go/bin/gofmt" ]]; then
    ln -sf ../runtime/go/bin/gofmt "$bin/gofmt"
  fi
  if [[ -x "$runtime/node/bin/node" ]]; then
    ln -sf ../runtime/node/bin/node "$bin/node"
  fi
  if [[ -e "$runtime/pnpm/bin/pnpm" ]]; then
    ln -sf ../runtime/pnpm/bin/pnpm "$bin/pnpm"
  fi
  return 0
}

build_candidate() {
  mkdir -p "$PROFILE_ROOT"

  if [[ -e "$FINAL_STATE" ]]; then
    if [[ ! -e "$FINAL_STATE/$INCOMPLETE_MARKER" ]]; then
      validate_profile_manifest "$FINAL_STATE"
      validate_profile_versions "$FINAL_STATE"
      verify_postconditions "$FINAL_STATE"
      [[ -x "$FINAL_STATE/activate.sh" ]] || die "existing profile state missing activation"
      return 0
    fi
    rm -rf "$FINAL_STATE"
  fi

  mkdir -p "$FINAL_STATE"
  touch "$FINAL_STATE/$INCOMPLETE_MARKER"

  cleanup_failed_state() {
    if [[ -e "$FINAL_STATE/$INCOMPLETE_MARKER" ]]; then rm -rf "$FINAL_STATE"; fi
  }
  trap cleanup_failed_state EXIT

  cp -a "$ROOT/payload/." "$FINAL_STATE/"
  cp "$ROOT/profile-toolchain.tsv" "$FINAL_STATE/profile-toolchain.tsv"
  cp "$ROOT/postconditions.tsv" "$FINAL_STATE/postconditions.tsv"
  touch "$FINAL_STATE/$MANAGED_MARKER"
  prepare_runtime_links "$FINAL_STATE"

  local bin="$FINAL_STATE/bin"
  local runtime="$FINAL_STATE/runtime"
  local cache="$FINAL_STATE/cache"
  export PATH="$bin:/usr/bin:/bin"

  if profile_needs_python; then
    [[ -x "$bin/uv" ]] || die "restored uv missing"
    export UV_PYTHON_INSTALL_DIR="$runtime/python"
    export UV_CACHE_DIR="$cache/uv"
    UV_GROUP_ARGS=(--group quality)
    [[ "$PROFILE" == "qa1" ]] && UV_GROUP_ARGS+=(--group qa1)
    [[ "$PROFILE" == "qa2" ]] && UV_GROUP_ARGS+=(--group qa2)
    UV_PROJECT_ENVIRONMENT="$FINAL_STATE/venv" \
      "$bin/uv" sync \
        --project "$FINAL_STATE/bootstrap-python" \
        --frozen \
        --offline \
        "${UV_GROUP_ARGS[@]}"
    [[ -x "$FINAL_STATE/venv/bin/python" ]] || die "restored venv missing Python"
  fi

  write_state_activation "$FINAL_STATE"
  validate_profile_manifest "$FINAL_STATE"
  validate_profile_versions "$FINAL_STATE"
  verify_postconditions "$FINAL_STATE"
  bash -n "$FINAL_STATE/activate.sh"
  rm -f "$FINAL_STATE/$INCOMPLETE_MARKER"
  trap - EXIT
}

commit_current() {
  # Single authoritative commit point. Candidate is already fully validated.
  rm -f "$CURRENT.tmp"
  ln -s "$BUNDLE_ID" "$CURRENT.tmp"
  mv -Tf "$CURRENT.tmp" "$CURRENT"
}

# Phase C: candidate materialize/validate. Previous current remains untouched on failure.
build_candidate

# Phase D: one atomic current switch after complete validation.
commit_current

log "RESTORE PASS: $PROFILE"
log "activate: source \"$PROFILE_ROOT/current/activate.sh\""
RESTORE
chmod +x "$ROOT/restore.sh"

cat > "$ROOT/README.md" <<EOF
# Flare dependency bundle — $PROFILE

## Verify archive before extraction

The detached checksum file contains only the archive basename:

\`\`\`bash
sha256sum -c ${NAME}.tar.gz.sha256
\`\`\`

## Extract

\`\`\`bash
tar -xzf ${NAME}.tar.gz
cd ${NAME}
\`\`\`

## Restore

\`\`\`bash
./restore.sh /path/to/flare
source /path/to/flare/.flare/profiles/$PROFILE/current/activate.sh
\`\`\`

Restore verifies internal payload integrity before touching the target repo.

It validates a versioned candidate state first and switches only the profile
current pointer after complete validation. It never touches the project .venv path.
EOF

# Internal manifest excludes itself by construction.
(
  cd "$ROOT"
  find . -type f ! -name SHA256SUMS -print0 \
    | sort -z \
    | xargs -0 sha256sum > SHA256SUMS
)

safe_symlinks "$ROOT"

# Prove internal manifest before packaging.
(cd "$ROOT" && sha256sum -c SHA256SUMS >/dev/null)

ARCHIVE="$OUT/$NAME.tar.gz"
(
  cd "$WORK"
  tar \
    --sort=name \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    --mtime='UTC 2020-01-01' \
    -czf "$ARCHIVE" \
    "$NAME"
)

# Detached checksum uses basename only.
(
  cd "$OUT"
  sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256"
)

# Archive contract checks before publication.
tar -tzf "$ARCHIVE" | awk -v root="$NAME/" '
  $0 !~ "^" root { bad=1; print "entry outside top-level root: " $0 > "/dev/stderr" }
  END { exit bad }
'

# Relative symlinks containing '..' are valid when their resolved target stays
# inside the bundle root (e.g. Node's bin/npm -> ../lib/node_modules/...).
# That condition was already checked by safe_symlinks() before packaging.
# Here only reject obviously absolute symlink targets in the serialized tar.
if tar -tvzf "$ARCHIVE" | grep -E ' -> /' >/dev/null; then
  die "absolute symlink detected in archive"
fi

if tar -tvzf "$ARCHIVE" | grep -E '/home/|/Users/' >/dev/null; then
  die "local workstation identity/path leaked into tar metadata"
fi

log "BUNDLE PASS: $ARCHIVE"
log "sha256: $(awk '{print $1}' "$ARCHIVE.sha256")"
