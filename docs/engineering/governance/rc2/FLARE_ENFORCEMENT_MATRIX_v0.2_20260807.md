---
title: "Flare — Enforcement Matrix"
document_id: "FLARE-ENFORCEMENT-MATRIX-0001"
version: "0.2"
status: "INITIAL TRACEABILITY CLASSIFICATION FOR CURRENT SCAFFOLD"
date: "2026-08-07"
language: "ru"
---

# Flare Enforcement Matrix v0.2

Отсутствующий target не бывает GREEN.

Состояния:

```text
NOT_APPLICABLE
PLANNED
ADVISORY
BLOCKING
```

Enforcement mode:

```text
TYPE/COMPILE
STATIC
CONTRACT
UNIT
INTEGRATION
E2E
RUNTIME OBSERVABILITY
HUMAN REVIEW
PRODUCT/TECHNICAL DECISION
```

| Rule ID(s) | Capability | Scope | State | Owner | Enforcement mode | Unique signal / invariant | Implementation/evidence reference | Promotion requirement |
|---|---|---|---|---|---|---|---|---|
| FLARE-STD-GOV-001 | Engineering governance | repo | ADVISORY | PO + Gatekeeper | HUMAN REVIEW | task challenge before code | Engineering Standard §1; handoff verdict | factual review + onboarding exercise |
| FLARE-STD-EVD-001 | Evidence provenance/model | repo | ADVISORY | Analyst + Gatekeeper | HUMAN REVIEW | expected != observed evidence | Standard §2; incident/repro template | representative repro artifacts |
| FLARE-STD-QLT-001, FLARE-STD-QLT-002 | Repository/custom gate policy | repo | ADVISORY | Quality | STATIC + UNIT | gate lifecycle + intentional RED | existing repo-policy checker; future gate tests | negative fixtures + stable CI |
| FLARE-STD-PLAT-002 | Bootstrap doctor contract | repo | ADVISORY | Platform | INTEGRATION | read-only/deterministic/secret-safe | bootstrap contract suite | clean-host positive/negative tests |
| FLARE-STD-PLAT-002 | Bootstrap install/restore contract | repo | ADVISORY | Platform + Quality | INTEGRATION | safe/idempotent/non-destructive | dependency bundle contract suite | fresh-directory + failure rollback tests |
| FLARE-STD-PLAT-001 | Makefile thin facade | repo | PLANNED | Quality | STATIC + HUMAN REVIEW | no second implementation language | project CLI/Makefile architecture test | real project CLI exists |
| FLARE-STD-PLAT-001 | GitHub logical CI contract | repo | PLANNED | Platform | CONTRACT | adapter calls project commands | CI contract manifest/test | first real quality lanes |
| FLARE-STD-PLAT-001 | GitLab parity contract | repo | NOT_APPLICABLE | Platform | CONTRACT | logical parity with GitHub | future CI parity test | GitLab adapter introduced |
| — | Python format/lint/type | sdk/python | PLANNED | QA1 | STATIC + TYPE/COMPILE | strict Python foundation | Tooling Profile; future pyproject/uv.lock | project manifest exists |
| — | Python architecture boundary | sdk/python | NOT_APPLICABLE | QA1 + Quality | STATIC | dependency direction | future architecture test | real package boundaries exist |
| — | Python code coverage ratchet | sdk/python | NOT_APPLICABLE | QA1 | UNIT | owned executable branch risk | future coverage report | executable SDK code exists |
| — | Go format/vet/static | backend | PLANNED | Backend | STATIC + TYPE/COMPILE | compile/static defects | future go.mod / check target | Go module/code exists |
| — | Go architecture boundary | backend | PLANNED | Backend + Quality | STATIC | domain dependency direction | future architecture test | package hierarchy exists |
| — | Go race evidence | backend | NOT_APPLICABLE | Backend | INTEGRATION | concurrency defects | future measured race lane | concurrency-sensitive code exists |
| — | DB migration compatibility | backend | NOT_APPLICABLE | Backend + QA1 | INTEGRATION | prior schema survives candidate | future migration suite | first migration exists |
| FLARE-STD-REL-001, FLARE-STD-REL-002, FLARE-STD-REL-003, FLARE-STD-REL-004, FLARE-STD-REL-005 | Ingestion Reliability | backend/API | NOT_APPLICABLE | QA1 | CONTRACT + INTEGRATION | ack/idempotency/order/recovery | future QA1 reliability suite | ingest exists |
| FLARE-STD-QA-001, FLARE-STD-QA-002 | Reporter Outcome Isolation | pytest SDK | NOT_APPLICABLE | QA1 | INTEGRATION | reporting cannot alter pytest outcome | future reporter fault suite | reporter exists |
| FLARE-STD-REL-005 | Persistence Recovery | backend/storage | NOT_APPLICABLE | QA1 | INTEGRATION | restart/recovery semantics | future recovery suite | persistence exists |
| FLARE-STD-SEC-001 | Redaction Boundary | end-to-end | NOT_APPLICABLE | QA1 | INTEGRATION | canary secrets blocked by threat model | future redaction suite | evidence paths exist |
| FLARE-STD-REL-006 | SSE replay/reconnect | backend/frontend | NOT_APPLICABLE | Backend + Frontend + QA | CONTRACT + INTEGRATION + E2E | replay cursor != producer sequence | future SSE contract suite | SSE exists |
| FLARE-STD-RES-001 | Bounded resource overflow | runtime | NOT_APPLICABLE | Component owner | CONTRACT + INTEGRATION + RUNTIME OBSERVABILITY | overflow semantics explicit | future resource contract/stress | first bounded queue/buffer exists |
| — | Contract format/lint | contracts | PLANNED | Backend | STATIC | schema quality | future Buf/protoc config | canonical schema selected |
| — | Contract breaking | contracts | PLANNED | Backend | CONTRACT | compatibility drift | future breaking gate | released contract baseline exists |
| — | Generated drift | contracts | PLANNED | Backend | CONTRACT | source/generated mismatch | future generation check | generator exists |
| — | Cross-language contract | contracts | PLANNED | Backend + QA1 + Frontend | CONTRACT | same semantics in 3 languages | future golden/round-trip tests | generated consumers exist |
| — | Frontend format/type | frontend | PLANNED | Frontend | STATIC + TYPE/COMPILE | TS format/type defects | future package.json/check target | frontend project exists |
| — | Frontend architecture | frontend | NOT_APPLICABLE | Frontend | STATIC | forbidden dependency direction | future architecture fixture | module boundaries exist |
| FLARE-STD-REL-006 | SSE lifecycle regression | frontend | NOT_APPLICABLE | Frontend | UNIT + INTEGRATION | leaked/stale subscriptions | future lifecycle tests | SSE consumer exists |
| FLARE-STD-TST-001 | Chromium Product E2E | product | NOT_APPLICABLE | QA2 | E2E | real user vertical with deterministic waits | future reference journey | vertical exists |
| FLARE-STD-TST-001 | E2E anti-pattern gate | tests/e2e | NOT_APPLICABLE | QA2 + Quality | STATIC | sleep/skip/retry misuse | future narrow AST rule | stable E2E structure exists |
| — | Accessibility automation | frontend/e2e | NOT_APPLICABLE | Frontend + QA2 | STATIC + E2E | machine-detectable a11y | future accessibility lane | first surface exists |
| — | Keyboard/focus acceptance | product | NOT_APPLICABLE | QA2 | E2E + HUMAN REVIEW | meaningful accessibility behavior | future critical journeys | first critical journey exists |
| — | Reference pytest workload | tests/reference | PLANNED | QA2 | CONTRACT | independent deterministic oracle | versioned reference dataset | dataset committed |
| FLARE-STD-PERF-001 | Performance baseline | product | NOT_APPLICABLE | Owners + QA | RUNTIME OBSERVABILITY | reproducible distribution/variance | future benchmark evidence | representative implementation exists |
| FLARE-STD-PERF-001 | Performance budget ratchet | product | NOT_APPLICABLE | PO + Engineering | PRODUCT/TECHNICAL DECISION + INTEGRATION | regression vs accepted budget | decision + benchmark gate | baseline/variance/budget accepted |
| FLARE-STD-SUP-001 | Supply-chain vulnerability | artifacts | PLANNED | Platform | STATIC | known vulnerable inputs | future artifact scan | first build artifact exists |
| FLARE-STD-SUP-001 | SBOM/provenance | release artifact | NOT_APPLICABLE | Platform | CONTRACT | source-to-artifact custody | future SBOM/provenance evidence | releasable artifact exists |
| FLARE-STD-SUP-001 | Signing/attestation | release | NOT_APPLICABLE | Platform + PO | PRODUCT/TECHNICAL DECISION + CONTRACT | artifact authenticity | future release policy | trigger accepted |
| FLARE-STD-PLAT-002, FLARE-STD-SEC-001 | Privacy-safe fingerprint | tooling | PLANNED | Platform + Quality | STATIC + UNIT | reproducible evidence without identity leakage | future fingerprint generator tests | generator exists |
| FLARE-STD-DOC-001 | Onboarding fresh-machine | repo | ADVISORY | Analyst + Platform | INTEGRATION + HUMAN REVIEW | no tribal knowledge | START-HERE + bootstrap exercise | bootstrap stabilizes |
| FLARE-STD-QLT-002, FLARE-STD-DOC-001 | Intentional RED onboarding | repo | PLANNED | Quality | INTEGRATION | newcomer sees real failing gate | first blocking gate mutation | first BLOCKING gate exists |

## Promotion rule

`PLANNED → ADVISORY → BLOCKING` требует:

```text
target exists
stable Rule ID where rule is mandatory/exception-targetable
owner
enforcement mode
positive case
intentional RED
legitimate exception where relevant
false-positive review
representative runtime measurement
implementation/evidence reference
documented failure semantics
```

## Downgrade rule

`BLOCKING → ADVISORY/OFF` только через exception:

```text
Rule ID
owner
incident/issue
evidence
risk
expiry
compensating control
removal condition
```
