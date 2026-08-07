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
if [ "${1:-}" = "-c" ]; then exit 0; fi
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

make_tool "$F/runtime/go/bin/go" 'go version go1.26.5 linux/amd64'
make_tool "$F/runtime/go/bin/gofmt" 'usage: gofmt [flags] [path ...]'
make_tool "$F/bin/goimports" 'goimports fake'
make_tool "$F/bin/staticcheck" 'staticcheck 2026.1 (v0.7.0)'
make_tool "$F/bin/golangci-lint" 'golangci-lint 1.fake'
make_tool "$F/bin/govulncheck" 'Go: go1.26.5'
make_tool "$F/bin/dlv" 'Delve Debugger Version: 1.fake'
make_tool "$F/bin/protoc-gen-go" 'protoc-gen-go v1.fake'
make_tool "$F/bin/buf" '1.72.0'
make_tool "$F/bin/protoc" 'libprotoc 35.1'

make_tool "$F/runtime/node/bin/node" 'v24.19.0'
make_tool "$F/runtime/pnpm/bin/pnpm" '11.20.0'
cp "$F/runtime/pnpm/bin/pnpm" "$F/bin/pnpm"

make_tool "$F/bin/kubectl" 'Client Version: v1.fake'
make_tool "$F/bin/helm" 'v3.fake'
make_tool "$F/bin/minikube" 'minikube version: v1.fake'
make_tool "$F/bin/hadolint" 'Haskell Dockerfile Linter 2.fake'
make_tool "$F/bin/actionlint" '1.fake'
make_tool "$F/bin/kubeconform" 'v0.fake'

cat > "$F/toolchain.lock.tsv" <<'EOF'
# name	version	source	sha256	kind
uv	0.fake	fake	-	cli
python	3.13.14	fake	-	runtime
go	1.26.5	fake	-	runtime
gofmt	1.26.5	fake	-	cli
goimports	fake	fake	-	cli
staticcheck	0.7.0	fake	-	cli
golangci-lint	fake	fake	-	cli
govulncheck	fake	fake	-	cli
dlv	fake	fake	-	cli
protoc-gen-go	fake	fake	-	cli
buf	1.72.0	fake	-	cli
protoc	35.1	fake	-	cli
node	24.19.0	fake	-	runtime
pnpm	11.20.0	fake	-	cli
kubectl	fake	fake	-	cli
helm	fake	fake	-	cli
minikube	fake	fake	-	cli
hadolint	fake	fake	-	cli
actionlint	fake	fake	-	cli
kubeconform	fake	fake	-	cli
EOF

for profile in backend frontend qa1 qa2 platform linter; do
  echo "[synthetic] $profile"
  "$HERE/accept_bundle.sh" "$profile" "$REPO" "$OUT"
done

echo "SYNTHETIC ALL-PROFILE ACCEPTANCE PASS"
