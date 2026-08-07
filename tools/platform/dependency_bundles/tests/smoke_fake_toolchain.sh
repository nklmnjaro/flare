#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "$SCRIPT_DIR/../flare-bundle.sh" ]]; then
  HERE="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  HERE="$(cd "$SCRIPT_DIR/../canonical" && pwd)"
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "[synthetic] intentional RED: pre-fix atomicity ordering reproduces old defect"
LEGACY="$TMP/legacy"
mkdir -p "$LEGACY/.flare/profiles/platform/old-state" "$LEGACY/.venv"
ln -s old-state "$LEGACY/.flare/profiles/platform/current"
printf 'do-not-touch\n' > "$LEGACY/.venv/sentinel"
if "$SCRIPT_DIR/fixtures/restore_pre_atomicity_ordering.sh" \
  "$LEGACY" platform broken-state >/dev/null 2>&1; then
  echo "[synthetic][ERROR] legacy fixture did not reject unmanaged .venv" >&2
  exit 1
fi
[[ "$(readlink "$LEGACY/.flare/profiles/platform/current")" == "broken-state" ]] || {
  echo "[synthetic][ERROR] legacy fixture no longer reproduces pre-fix mutation" >&2
  exit 1
}
REPO="$TMP/flare"
OUT="$TMP/out"
F="$REPO/.flare"
mkdir -p "$F/bin" "$F/runtime/python" "$F/runtime/go/bin" \
  "$F/runtime/node/bin" "$F/runtime/pnpm/bin" "$F/cache/uv" \
  "$F/bootstrap-python" "$F/include" "$OUT"

cat > "$F/bootstrap-python/pyproject.toml" <<'EOF'
[project]
name = "fake"
version = "0.0.0"
requires-python = ">=3.13,<3.14"
[dependency-groups]
quality = []
qa1 = []
qa2 = []
EOF
printf 'version = 1\n' > "$F/bootstrap-python/uv.lock"

make_tool() {
  local path="$1" output="$2"
  cat > "$path" <<EOF
#!/bin/sh
printf '%s\\n' '$output'
EOF
  chmod +x "$path"
}

# Fake uv supports the only operation used by canonical builder/restore: sync.
cat > "$F/bin/uv" <<'UV'
#!/bin/sh
set -eu
if [ "${1:-}" != "sync" ]; then
  echo "uv 0.fake"
  exit 0
fi
: "${UV_PROJECT_ENVIRONMENT:?missing UV_PROJECT_ENVIRONMENT}"
mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
cat > "$UV_PROJECT_ENVIRONMENT/bin/python" <<'PY'
#!/bin/sh
if [ "${1:-}" = "--version" ]; then echo 'Python 3.13.14'; exit 0; fi
if [ "${1:-}" = "-c" ]; then echo '3.13.14'; exit 0; fi
exit 0
PY
chmod +x "$UV_PROJECT_ENVIRONMENT/bin/python"
for spec in \
  'pytest:pytest 9.1.1' \
  'ruff:ruff 0.16.1' \
  'mypy:mypy 2.3.0 (compiled: yes)' \
  'pylint:pylint 4.0.6' \
  'pre-commit:pre-commit 4.0.0'; do
  name="${spec%%:*}"
  out="${spec#*:}"
  cat > "$UV_PROJECT_ENVIRONMENT/bin/$name" <<EOF
#!/bin/sh
printf '%s\\n' '$out'
EOF
  chmod +x "$UV_PROJECT_ENVIRONMENT/bin/$name"
done
UV
chmod +x "$F/bin/uv"
cp "$F/bin/uv" "$F/bin/uvx"

cat > "$F/runtime/go/bin/go" <<'GO'
#!/bin/sh
set -eu
if [ "${1:-}" = "version" ] && [ "${2:-}" = "-m" ]; then
  name="$(basename "${3:?missing binary}")"
  case "$name" in
    goimports) module="golang.org/x/tools"; version="v0.fake" ;;
    staticcheck) module="honnef.co/go/tools"; version="v0.7.0" ;;
    govulncheck) module="golang.org/x/vuln"; version="v0.fake" ;;
    dlv) module="github.com/go-delve/delve"; version="v1.fake" ;;
    protoc-gen-go) module="google.golang.org/protobuf"; version="v1.fake" ;;
    *) exit 1 ;;
  esac
  printf '%s: go1.26.5\n\tmod\t%s\t%s\n' "${3}" "$module" "$version"
  exit 0
fi
printf '%s\n' 'go version go1.26.5 linux/amd64'
GO
chmod +x "$F/runtime/go/bin/go"
make_tool "$F/runtime/go/bin/gofmt" 'usage: gofmt [flags] [path ...]'
make_tool "$F/bin/goimports" 'goimports fake'
make_tool "$F/bin/staticcheck" 'staticcheck 2026.1 (v0.7.0)'
make_tool "$F/bin/golangci-lint" 'golangci-lint has version 1.fake built with go1.26.5'
make_tool "$F/bin/govulncheck" 'Scanner: govulncheck@v0.fake'
make_tool "$F/bin/dlv" 'Delve Debugger Version: v1.fake'
make_tool "$F/bin/protoc-gen-go" 'protoc-gen-go v1.fake'
make_tool "$F/bin/buf" '1.72.0'
make_tool "$F/bin/protoc" 'libprotoc 35.1'

make_tool "$F/runtime/node/bin/node" 'v24.19.0'
make_tool "$F/runtime/pnpm/bin/pnpm" '11.20.0'
cp "$F/runtime/pnpm/bin/pnpm" "$F/bin/pnpm"

cat > "$F/bin/kubectl" <<'KUBECTL'
#!/bin/sh
case "$*" in
  *"-o json"*|*"--output=json"*)
    printf '%s\n' '{"clientVersion":{"gitVersion":"v1.fake"}}'
    ;;
  *)
    printf '%s\n' 'Client Version: v1.fake'
    ;;
esac
KUBECTL
chmod +x "$F/bin/kubectl"
make_tool "$F/bin/helm" 'v3.fake'
cat > "$F/bin/minikube" <<'MINIKUBE'
#!/bin/sh
if [ "${2:-}" = "--short" ] || [ "${1:-}" = "--short" ]; then
  printf '%s\n' 'v1.fake'
else
  printf '%s\n' 'minikube version: v1.fake'
fi
MINIKUBE
chmod +x "$F/bin/minikube"
make_tool "$F/bin/hadolint" 'Haskell Dockerfile Linter 2.fake'
make_tool "$F/bin/actionlint" '1.fake'
make_tool "$F/bin/kubeconform" 'v0.fake'

cat > "$F/toolchain.lock.tsv" <<'EOF'
# name	version	source	sha256	kind
uv	0.fake	fake	-	cli
python	3.13.14	fake	-	runtime
go	1.26.5	fake	-	runtime
gofmt	1.26.5	fake	-	cli
goimports	v0.fake	fake	-	cli
staticcheck	v0.7.0	fake	-	cli
golangci-lint	1.fake	fake	-	cli
govulncheck	v0.fake	fake	-	cli
dlv	v1.fake	fake	-	cli
protoc-gen-go	v1.fake	fake	-	cli
buf	1.72.0	fake	-	cli
protoc	35.1	fake	-	cli
node	24.19.0	fake	-	runtime
pnpm	11.20.0	fake	-	cli
kubectl	1.fake	fake	-	cli
helm	3.fake	fake	-	cli
minikube	1.fake	fake	-	cli
hadolint	2.fake	fake	-	cli
actionlint	1.fake	fake	-	cli
kubeconform	0.fake	fake	-	cli
EOF

for profile in backend frontend qa1 qa2 platform linter; do
  echo "[synthetic] $profile"
  "$HERE/accept_bundle.sh" "$profile" "$REPO" "$OUT"
done

echo "SYNTHETIC ALL-PROFILE ACCEPTANCE PASS"
