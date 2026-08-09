---
title: "Flare — Engineering Standard Review Decisions"
document_id: "FLARE-ENGINEERING-STANDARD-CONSOLIDATION-0002"
version: "0.2"
status: "ANALYST CONSOLIDATION"
date: "2026-08-07"
language: "ru"
---

# Consolidation Decisions

## 1. Consensus

Все пять role reviews + Product Owner сходятся:

1. task challenge остаётся обязательным;
2. Smallest Correct Change остаётся;
3. Quality Ratchet и adversarial gate tests остаются;
4. normative contract отделяется от observed evidence;
5. evidence требует provenance;
6. Makefile = facade, CI = adapters;
7. gate lifecycle и applicability обязательны;
8. tools не являются вечными laws;
9. static proof не симулируется там, где нужен runtime/design/review;
10. finite request и long-lived stream различаются;
11. durable ACK/batch/idempotency semantics требуют усиления;
12. accepted/projected/visible различаются;
13. bounded resource требует overflow contract;
14. Product E2E ждёт observable condition, не время;
15. performance threshold требует baseline/variance;
16. onboarding/continuity не ослабляются.

## 2. Реальные противоречия и решения

### C-01 Evidence Completeness names

QA №1 предлагал альтернативные названия состояния.

Решение:

```text
REJECT CHANGE
```

Сохраняется Product Decision:

```text
COMPLETE
PARTIAL
UNKNOWN
```

Reporter degradation — отдельная ось.

### C-02 "Durable SSE cursor"

Часть формулировок могла читаться как отдельная persistence entity.

Решение:

```text
server-issued replay cursor
whose referenced position survives restart
within documented replay window
```

Не навязывается отдельная cursor table/entity.

### C-03 Zero permanent skips

Абсолютный ban уточнён.

Сохраняется:

```text
0 permanent/unexplained behavioral skips
```

Допускаются objective platform capability и временный quarantine с
owner/issue/expiry/removal condition.

### C-04 Race detector

Race evidence required for concurrency-sensitive Go.

Физическая lane определяется измерением; global `-race ./...` в fast loop
не является законом.

### C-05 Tool lists

Ruff/Pylint/Biome/Trivy/staticcheck/etc не остаются вечными architecture laws.

Они вынесены в Tooling Profile.

## 3. Engineering decisions

Принято:

```text
Standard = invariants/capabilities
Tooling Profile = current tools
Enforcement Matrix = maturity/applicability

Makefile = facade
project CLI/tested scripts = executable truth
CI providers = adapters

gate lifecycle:
NOT_APPLICABLE / PLANNED / ADVISORY / BLOCKING

custom gate:
positive + intentional RED + false-positive review

bootstrap:
doctor read-only
system mutation explicit opt-in

environment fingerprint:
privacy-safe

quality:
unique signal over tool count
```

## 4. Product/Technical decisions, не замороженные Standard

Нужны owners/decision records:

```text
exact durable ACK transaction boundary
batch atomic vs per-event acceptance
producer incarnation/restart semantics
SSE replay retention
stale cursor behavior
event/batch/attachment limits
late mandatory evidence finalization
latency SLA/budget
visual regression MVP scope
signing/attestation trigger
supported developer host matrix
local Kubernetes choice where unresolved
```

## 5. Уже сохранённое Product Decision

```text
Evidence Completeness:
COMPLETE / PARTIAL / UNKNOWN
```

Known mandatory evidence loss запрещает `COMPLETE`.

## 6. Rejected suggestions

Не принимаются как authoritative rules:

```text
Python Feature Plane runtime
QA-R mega-suite как обязательный MVP пакет прямо сейчас
новый linter на каждый review comment
tool names как вечные architecture laws
blanket grep/AST ban любых goroutine/SQL/time.Sleep/setTimeout
global go test -race in every fast run
blanket visual regression
browser-test Python line coverage как product KPI
GitHub-first/GitLab-second rollout order как perpetual law
generic scanner как proof of no secrets
accessibility scanner как sole oracle
```

## 7. Следующий review

RC1 отдаётся:

```text
Product Owner
Gatekeeper
Quality/Linter owner
```

Задача reviewer:

```text
не предлагать больше правил ради количества;
искать contradiction, frozen product decisions,
false machine-proof, missing ownership,
unbounded behavior и unenforceable wording.
```


# RC1 factual review amendments accepted

## GOV-001

Accepted.

Stable Rule IDs added only for mandatory invariants that need gate/test/
exception traceability.

Enforcement Matrix now has:

```text
Rule ID(s)
Enforcement mode
Implementation/evidence reference
```

## GOV-002

Accepted.

`uv` removed from Engineering Standard.

Capability remains:

```text
one canonical, locked, reproducible Python package/environment workflow
```

Current implementation `uv` remains only in Tooling Profile/toolchain manifest.

## GOV-003

Accepted.

Declarative-only `CHECKS.txt` replaced with:

```text
tools/verify_governance.py
tests/test_verify_governance.py
CHECKS.md
```

Verifier has intentional negative mutations.

Final archive receives detached checksum using artifact basename only.
