---
title: "Flare — Tooling Profile"
document_id: "FLARE-TOOLING-PROFILE-0001"
version: "0.2"
status: "CANDIDATE IMPLEMENTATION BASELINE"
date: "2026-08-07"
language: "ru"
---

# Flare Tooling Profile v0.2

Этот документ не является архитектурным законом.

Engineering Standard определяет capabilities.
Tooling Profile фиксирует текущую preferred implementation.

Каждый tool остаётся только пока даёт уникальный или существенно лучший signal.

Exact versions фиксируются toolchain manifest/lock-файлами.

## 1. Common

```text
Git
Makefile как facade
project CLI/tested scripts как executable source of truth
pre-commit — conditional after real hooks exist
```

## 2. Python 3.13

Package/environment manager:

```text
uv
```

Запрещено иметь параллельный pip-based project workflow.

Base capabilities:

```text
Ruff format
Ruff check
mypy --strict
pytest
dependency/security audit
```

Conditional:

```text
Pylint — только unique signal
Import Linter — после появления real package boundaries
coverage — owned executable code
custom AST gates — только narrow proven defect classes
```

QA1 conditional stack after project manifests exist:

```text
pytest-xdist
pytest-timeout
pytest-asyncio
httpx
psycopg
S3-compatible client/testing tooling
```

QA2:

```text
pytest
Playwright Python
Chromium only for MVP
```

## 3. Go Backend

Base:

```text
gofmt
goimports
go vet
staticcheck
go test
govulncheck
```

Conditional/complementary:

```text
golangci-lint selected non-duplicate analyzers
go test -race in measured concurrency/full lanes
Delve for development/debugging, not quality proof
```

Avoid:

```text
duplicate staticcheck signal
blanket AST bans for goroutines/timeouts/SQL
ORM without proven need
DI container by default
```

## 4. Frontend

Runtime/package:

```text
Node LTS
pnpm
TypeScript strict
SolidJS
Vite
```

Quality:

```text
Biome
tsc --noEmit
Vitest
Testing Library when component tests exist
```

Conditional:

```text
Playwright Chromium — after first real vertical
accessibility automation — complementary
dead-code tooling — after entry-point baseline
bundle/performance gates — after reproducible baseline
```

Do not add by default:

```text
second formatter/linter
state manager
frontend BFF
SSR framework
blanket visual regression
```

## 5. Contracts

Candidate baseline:

```text
Protocol Buffers
protoc
Buf
generated Go/Python/TypeScript contracts
```

Before becoming BLOCKING, owners must confirm generator strategy and
cross-language compatibility.

Capabilities:

```text
format
lint
breaking
generation drift
round-trip/golden
unknown-version behavior
```

## 6. Platform

Current candidate tools by capability:

```text
Shell static quality        → ShellCheck
GitHub workflow semantics   → actionlint
Dockerfile static quality   → Hadolint
Kubernetes schema           → kubeconform
Kubernetes CLI              → kubectl
Helm                        → helm
Local Kubernetes            → Minikube where currently selected
Container vulnerability     → one primary scanner after selection
SBOM                        → one primary generator after selection
```

Не добавлять несколько vulnerability/YAML tools без unique signal.

## 7. Supply chain

Tool choice может меняться, capabilities нет:

```text
dependency vulnerability
container vulnerability
SBOM
provenance
signing/attestation when trigger accepted
```

## 8. Tool admission rule

Перед новым tool:

```text
risk solved
unique signal
owner
runtime cost
false-positive risk
maintenance
security/provenance
removal cost
```

Tool без доказанной пользы не принимается.

## 9. Versioning

Tool version обновляется отдельным evidence-backed change.

Update обязан показать применимое:

```text
release notes
compatibility
lock/manifest diff
affected gates
negative fixtures still RED
new warnings/noise
rollback
```
