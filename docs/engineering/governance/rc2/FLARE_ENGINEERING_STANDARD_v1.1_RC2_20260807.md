---
title: "Flare — Engineering Standard"
document_id: "FLARE-ENGINEERING-STANDARD-0001"
version: "1.1-rc2"
status: "FOR PRODUCT OWNER + GATEKEEPER REVIEW"
date: "2026-08-07"
language: "ru"
supersedes_candidate: "v1.0 after five role challenge reviews"
---

# Flare — Engineering Standard v1.1 RC1

## 0. Назначение

Этот документ сохраняет культурное и инженерное ядро v1.0, но отделяет
устойчивые engineering laws от конкретных инструментов и незакрытых runtime
Product Decisions.

Культурный цикл:

```text
Criticize
→ Prove
→ Simplify
→ Implement minimally
→ Verify independently
→ Harden the gate
→ Capture the knowledge
→ Challenge again
```

Production scope не расширяется этим документом.

До отдельного `APPROVE FLARE-000` запрещено материализовывать неутверждённые
runtime contracts и deferred architecture.

---

# 1. Critical Engineering Contract

Инженер не является генератором кода.

Любая задача, ADR, acceptance criterion, существующий код, тест или указание
является гипотезой до проверки применимых предпосылок:

```text
problem
evidence
user/product value
authoritative boundary contract
failure modes
security
observability
resource behavior
migration/rollback
acceptance criteria
owner
scope/non-goals
```

Допустимые verdict:

```text
TASK ASSUMPTION INVALID
SCOPE CORRECTION REQUIRED
SIMPLER SOLUTION PROPOSED
INSUFFICIENT EVIDENCE
PRODUCT DECISION REQUIRED
DO NOT IMPLEMENT
```

Возражение содержит:

```text
assumption
evidence
risk
simpler alternative
required decision
verification
```

Слепое выполнение слабой постановки считается инженерным дефектом.

---

# 2. Product/Technical Evidence Model

## 2.1. Что должно происходить

Normative sources:

```text
accepted product/security decision
→ versioned public/domain/protocol contract
→ accepted normative ADR/RFC
→ accepted acceptance criteria
```

## 2.2. Что происходит сейчас

Diagnostic evidence:

```text
reproducible runtime evidence
→ exact deployed/source artifact
→ focused reproducer
→ source + automated tests interpreted together
→ logs/docs/history
```

Evidence должно быть provenance-aware. Где применимо, фиксируются:

```text
commit/artifact
environment
protocol/schema version
dataset
exact command
timeout
result
limitations
```

При конфликте expected/actual не выбирается «верхний источник».
Классифицируется:

```text
product defect
implementation defect
stale contract
stale test
stale deployment
insufficient evidence
product/engineering decision required
```

Automated test не становится product contract автоматически.

---

# 2A. Stable Rule IDs для traceability

Stable Rule ID назначается не каждой строке документа, а только обязательным
invariant, на который могут ссылаться gate, test, exception или decision.

```text
FLARE-STD-GOV-001  Task assumptions are challenged before implementation.
FLARE-STD-EVD-001  Normative expected behavior and diagnostic evidence are distinct.
FLARE-STD-REL-001  Delivery is at-least-once with idempotent ingestion; no global order.
FLARE-STD-REL-002  Successful producer ACK has explicit durability semantics.
FLARE-STD-REL-003  Batch acceptance is explicitly atomic or per-event.
FLARE-STD-REL-004  Conflicting duplicate identity is an integrity/protocol conflict.
FLARE-STD-REL-005  Accepted/persisted/projected/query/SSE/UI states are distinct.
FLARE-STD-REL-006  Producer sequence is not the browser replay cursor.
FLARE-STD-RES-001  Every bounded queue/buffer/pool has explicit overflow semantics.
FLARE-STD-QA-001   Flare reporter failure does not change pytest outcome.
FLARE-STD-QA-002   Known mandatory evidence loss forbids COMPLETE.
FLARE-STD-QLT-001  Gate maturity is N/A/PLANNED/ADVISORY/BLOCKING.
FLARE-STD-QLT-002  Custom blocking gates prove an intentional RED mutation.
FLARE-STD-TST-001  Elapsed time is not a readiness signal in integration/browser tests.
FLARE-STD-SEC-001  Security claims are bounded by an explicit threat model.
FLARE-STD-PLAT-001 Makefile is a facade; CI providers are adapters.
FLARE-STD-PLAT-002 Bootstrap is safe/idempotent; system mutation is explicit opt-in.
FLARE-STD-SUP-001  Release artifacts preserve source-to-artifact chain of custody.
FLARE-STD-DOC-001  Critical knowledge is reproducible without chat history.
FLARE-STD-PERF-001 Numerical performance budgets require baseline and variance first.
```

Enforcement details и maturity находятся в `FLARE_ENFORCEMENT_MATRIX`, а
конкретные tools — в `FLARE_TOOLING_PROFILE`.

---

# 3. Smallest Correct Change

Предпочтение:

```text
одна подтверждённая проблема
→ минимальное достаточное решение
→ независимая проверка
→ regression/ratchet
→ понятный rollback
```

До новой abstraction/dependency/service/cache/queue/state спросить:

```text
можно удалить?
можно решить существующим stack?
есть ли реальный второй consumer/use case?
измерена ли проблема?
```

Запрещено расширять scope «заодно».

MVP не получает новые runtime units только ради future flexibility.

---

# 4. Runtime & Resource Invariants

## 4.1. Delivery и ordering

Базовая модель:

```text
at-least-once producer delivery
+
idempotent server ingestion
```

Обязательно:

```text
event identity
producer identity
sequence ownership
producer incarnation/restart semantics
duplicate semantics
conflicting duplicate semantics
```

Global event ordering не предполагается.

```text
same event identity + same canonical content
→ idempotent duplicate

same event identity + conflicting canonical content
→ integrity/protocol conflict
```

## 4.2. Durable acknowledgement

Successful producer acknowledgement имеет точное versioned durability meaning.

Контракт обязан отвечать:

> Что уже обязано пережить restart после success response?

Различаются:

```text
accepted
durably persisted
projected
query-visible
SSE-visible
UI-visible
```

Projection/UI/read model не являются sole oracle canonical durability.

## 4.3. Batch acceptance

До реализации retry behavior явно выбирается:

```text
atomic batch
или
explicit per-event acceptance
```

Unknown partial acceptance недопустим.

Точное решение остаётся в `FLARE-000`/decision register.

## 4.4. Canonical facts и projections

Accepted canonical facts append-only в пределах versioned contract.

Projection:

```text
checkpointed
rebuildable
restart-safe
observable when lagging/degraded
```

Projection lag/failure не переписывает уже подтверждённую durable acceptance.

## 4.5. SSE

```text
producer sequence != browser replay cursor
```

SSE использует server-issued replay cursor, позиция которого восстанавливается
из restart-surviving server state в пределах документированного replay/
retention window.

Если cursor недоступен:

```text
explicit resync
→ current snapshot/read model
→ resume live
```

Точный retention/stale-cursor behavior — Product/Technical Decision.

## 4.6. Finite operations vs long-lived streams

Finite request:

```text
deadline/timeout
cancellation
bounded retry where applicable
```

Long-lived stream:

```text
explicit owner
close/cancellation
liveness policy
bounded reconnect/backoff
resync behavior
observability
```

Обычный short-request timeout не навязывается SSE.

## 4.7. Bounded resources

Каждая queue/buffer/pool имеет:

```text
owner
capacity
overflow policy
backpressure policy
durability impact
Evidence Completeness impact
metric
cancellation
shutdown behavior
```

`bounded` без overflow semantics — неполный contract.

Slow browser/client не блокирует canonical ingest.

## 4.8. Reporter isolation

Flare reporting failure не меняет pytest outcome.

Применимые faults обязаны сохранять:

```text
original pytest exit code
original test exception
bounded shutdown
observable degradation
honest Evidence Completeness
```

## 4.9. Evidence Completeness

MVP product model сохраняется:

```text
COMPLETE
PARTIAL
UNKNOWN
```

с machine-readable reasons.

Reporter degradation — отдельное понятие.

Known mandatory evidence loss запрещает `COMPLETE`.

Изменение этих состояний требует отдельного Product Decision.

---

# 5. Quality Ratchet

Найденная слабость проходит:

```text
reproduce
→ classify root cause
→ fix
→ regression
→ move detection earlier
→ adversarially test the guard
→ capture invariant/knowledge
```

Предпочтительный уровень защиты:

```text
compiler/type system
→ versioned/generated contract
→ static/architecture gate
→ unit/property/fuzz
→ integration/recovery
→ Product E2E
→ human review
```

Но syntax не подменяет semantic proof.

Если свойство нельзя надёжно доказать статически:

```text
controlled boundary
+ targeted rule
+ runtime/contract tests
+ review
```

лучше шумного blanket checker.

---

# 6. Gate Lifecycle & Applicability

## 6.1. Lifecycle

Каждая quality capability:

```text
NOT_APPLICABLE
PLANNED
ADVISORY
BLOCKING
```

Promotion:

```text
implementation exists
→ positive test
→ intentional RED mutation
→ legitimate-exception test where needed
→ false-positive review
→ representative use
→ stable signal
→ BLOCKING
```

`PLANNED` не изображает зелёный check.

`BLOCKING` нельзя downgrade без exception protocol.

## 6.2. Applicability

Для каждого area/package:

```text
REQUIRED
CONDITIONAL
NOT_APPLICABLE
```

Для gate фиксируются:

```text
risk class
unique signal
owner
lane
failure semantics
false-positive policy
promotion trigger
what the gate does NOT prove
```

Tool без уникального полезного signal удаляется или становится non-blocking.

## 6.3. Custom gates

Custom checker — production code.

Минимальный hardening:

```text
known-good
intentional violation
legitimate exception
malformed input
missing/stale data
deterministic exit/result
```

Gate без доказанного RED mutation не считается готовым.

---

# 7. Language & Layer Capabilities

Конкретные инструменты живут в `FLARE_TOOLING_PROFILE`, а Standard фиксирует
capabilities.

## 7.1. Go

Обязательные по применимости:

```text
format/import discipline
static analysis
architecture boundaries
unit/integration
vulnerability evidence
race/concurrency evidence для concurrency-sensitive code
migration compatibility при появлении migrations
```

Не объявляются полностью static-proof:

```text
goroutine ownership
transaction correctness
dependency necessity
timeout sufficiency
```

Raw application SQL живёт в persistence boundary.

Явные допустимые scopes:

```text
migrations
migration verification
DB test fixtures
approved diagnostics
```

`time.Sleep` запрещён как readiness/polling/synchronization/lifecycle mechanism.
Cancellable backoff использует корректную timer/context semantics.

## 7.2. Python / pytest SDK / QA

Обязательные по применимости:

```text
strict typing
format/lint
tests
contract/reliability evidence
security/dependency evidence
architecture boundaries при появлении реальных boundaries
```

Python project имеет один canonical, locked и воспроизводимый package/environment workflow.

`Any` допускается только на реальной dynamic boundary с локальной validation и
быстрым narrowing.

## 7.3. Frontend

Handwritten TypeScript:

```text
explicit any forbidden
```

Generated/vendor code не переписывается вручную ради этого правила.
Handwritten boundary остаётся strict.

Независимые state axes:

```text
business lifecycle
transport connectivity
protocol compatibility
local UI state
```

Reconnect не равен product failure.

Browser resources имеют owner/cleanup/bounded lifetime:

```text
EventSource/stream
AbortController
timer
observer
DOM listener
Object URL
worker
subscription
```

## 7.4. Contracts

Canonical DTO/protocol не дублируются вручную между Go/Python/TypeScript.

По зрелости обязательны:

```text
format/lint
breaking compatibility
generation drift
golden/round-trip
unknown version/status handling
cross-language compatibility
```

---

# 8. Test Engineering

## 8.1. Ownership

Каждый test имеет одного primary owner.

Developers владеют component/unit/integration tests своего кода.

QA №1 владеет независимыми capability families:

```text
Ingestion Reliability
Reporter Outcome Isolation
Persistence Recovery
Redaction Boundary
Custom Gate Mutation
```

Эти capability families становятся blocking только при появлении
соответствующего production path.

QA №2 владеет Product E2E/Browser acceptance и независимым reference workload.

## 8.2. Deterministic synchronization

Elapsed time не является readiness signal.

Разрешено ждать:

```text
observable product condition
versioned backend/read-model condition
explicit deterministic test checkpoint
```

Любой wait bounded и при timeout возвращает diagnostics.

`time.sleep`/`waitForTimeout` для readiness запрещены.

## 8.3. Reference journeys

Critical verticals используют versioned deterministic reference datasets:

```text
dataset ID/version
test inventory
expected outcomes
observable milestones
controlled failure
machine-readable expectations
no production secrets
```

Expected result меняется как reviewed contract change.

Flare UI не является sole oracle Flare.

## 8.4. Coverage

Для owned executable/library/framework code применяется code/branch coverage
как ratchet, если метрика отражает реальный риск.

Для Product E2E:

```text
acceptance criteria coverage
journey coverage
state coverage
failure-mode coverage
risk coverage
```

Количество E2E tests и Python coverage browser-suite кода не KPI.

## 8.5. Skips/retries

Цель:

```text
0 permanent/unexplained behavioral skips
0 retry-driven green CI
```

Допустимы только:

```text
objective platform capability condition
temporary quarantine
```

с:

```text
reason
owner
issue
expiry
removal condition
```

Product bug не превращается в skip.

---

# 9. Security & Supply Chain

Security claims ограничены explicit threat model.

Generic scanner не доказывает отсутствие всех секретов.

Применимые redaction/security tests используют synthetic canary secrets и
known secret classes.

Ownership:

```text
pytest producer:
pre-send redaction/classification

Go Core:
pre-persistence validation/redaction

frontend:
safe rendering; no client-side secret persistence; no raw evidence execution
```

Frontend считает untrusted:

```text
logs
tracebacks
HTTP bodies
attachment names/content
external URLs
html/markdown-like evidence
```

Raw HTML execution требует отдельного sanitizer/sandbox/CSP contract.

Supply-chain invariant:

```text
source revision
→ build inputs
→ artifact/image digest
→ SBOM
→ vulnerability result
→ provenance/signature when required
→ deployed revision
```

Плюс:

```text
least privilege CI permissions
reviewed action/dependency provenance
immutable pinning where security/release-sensitive
no unreviewed remote-script execution
short-lived identity preferred
explicit CI timeouts
no release identity based on latest
no secrets in image layers/history
```

Signing/attestation blocking trigger — отдельное decision.

---

# 10. Platform / Bootstrap / CI Parity

## 10.1. Executable source of truth

```text
Canonical executable logic
→ testable project CLI/modules/scripts

Makefile
→ thin ergonomic facade

GitHub Actions / GitLab CI
→ thin provider adapters
```

Makefile/CI YAML не реализуют вторично:

```text
complex parsing
retry/backoff
release state machines
secret handling
deployment verification algorithms
business/contract logic
```

## 10.2. CI parity

Поддерживаемые providers реализуют один machine-checkable logical capability
contract.

Физические jobs могут различаться.

Provider rollout order — roadmap decision, не вечный engineering law.

## 10.3. Bootstrap

`doctor`:

```text
read-only
deterministic
secret-safe
```

`bootstrap`:

```text
idempotent
project/user-local by default
no root by default
version-aware
preserves compatible existing tool
actionable remediation
system mutation only explicit opt-in
```

Toolchain manifest фиксирует:

```text
tool
version/range
required/optional
install strategy
provenance/checksum
owner
update policy
```

## 10.4. Privacy-safe environment fingerprint

Допустимо автоматически:

```text
OS/version
kernel
architecture
CPU/quota
RAM/limit
tool versions
repo revision/dirty state
lock hashes
runtime topology
exact command
timeout
artifact hashes
```

Не собирается автоматически:

```text
username
hostname
home path
full environment dump
tokens
proxy credentials
kubeconfig
registry credentials
private network identifiers
```

Generator имеет privacy/secret negative fixtures.

---

# 11. Performance & Accessibility

Численный performance budget становится blocking только после:

```text
reference scenario/dataset
environment fingerprint
measurement contract
baseline distribution
variance
accepted budget
```

Heavy browser performance/memory может жить в отдельной lab/release lane.

Latency contract определяет:

```text
start observation
end observation
correlation ID
clock semantics
reference environment
percentile/budget
```

Automated accessibility scanner — complementary signal.

Применимы также:

```text
keyboard
focus
semantic status meaning
non-color-only critical status
live/reconnect understandability
```

---

# 12. Documentation / Onboarding / Continuity

`bus factor = 1` — engineering defect.

Canonical entry point:

```text
docs/onboarding/START-HERE.md
```

Fresh-machine exercise:

```text
clean checkout
→ doctor
→ bootstrap
→ check-fast
→ minimal reference flow
→ intentional RED mutation
```

Критичное знание не остаётся только в chat/review.

После существенного finding оно переносится в применимое:

```text
contract
ADR/decision
test
gate
runbook
onboarding
```

Role-specific guides не копируют shared laws из Engineering Standard.

Они содержат только role-specific implementation guidance.

---

# 13. Zero-noise & Exceptions

Blocking lanes стремятся к:

```text
0 unexplained project-owned actionable warnings
0 hidden failed checks
0 unowned suppressions
```

Upstream warning классифицируется и не скрывается глобально.

Temporary exception содержит:

```text
owner
reason
issue
expiry
compensating control
removal condition
```

Exception не меняет product contract молча.

---

# 14. Ready / Done / Handoff

## Definition of Ready

Production implementation не начинается без применимых:

```text
problem/evidence
user outcome
authoritative contract
acceptance criteria
failure scenarios
security
observability
resource semantics
scope/non-goals
owner
migration/rollback
success measure
```

## Definition of Done

Change не Done без применимого evidence:

```text
implementation
format/lint/type
architecture
contract
unit/integration/E2E
reliability/recovery
security
dependency/provenance
migration
observability
performance where affected
docs
regression/ratchet
reproducible handoff
```

## Handoff

Содержит:

```text
Role / Task ID
Baseline
Assumptions reviewed/rejected
Scope corrections/simplifications
Files
Contract/migration/dependency impact
Security/performance impact
Exact checks/results
Checks not run + risk
Negative gate evidence
Known failures
Suppressions
Shared conflicts
Integration order
Rollback
Artifact SHA-256
```

---

# 15. AI-assisted development

AI-generated code рассматривается как untrusted candidate code.

Автор обязан понимать и защищать:

```text
contracts
lifecycle
failure modes
security
dependencies
tests/evidence
removal/rollback
```

Большое количество тестов не заменяет понимание.

---

# 16. Product Decisions, которые Standard не замораживает

Standard требует решения до реализации соответствующего path, но не
придумывает значения:

```text
exact durable-ack transaction semantics
batch atomicity/per-event semantics
producer incarnation/restart semantics
SSE replay retention window
stale cursor behavior
event/batch/attachment limits
late mandatory evidence finalization
latency SLA/budget
visual regression MVP scope
signing/attestation trigger
supported developer host matrix
local Kubernetes choice where unresolved
```

Отдельное уже принятое Product Decision:

```text
Evidence Completeness MVP:
COMPLETE / PARTIAL / UNKNOWN
```

---

# 17. Governance

Путь принятия:

```text
Analyst RC
→ Product Owner + Gatekeeper factual review
→ findings
→ Analyst amendment
→ short re-review
→ MANDATORY
```

После принятия конкретные tools живут в versioned Tooling Profile, а
enforcement maturity — в Enforcement Matrix.

---

# 18. Финальный договор

```text
Criticize
→ Prove
→ Simplify
→ Implement minimally
→ Verify independently
→ Harden the gate
→ Capture the knowledge
→ Challenge again
```

> Строгость — не максимальное число blocking rules.

> Строгость — это минимальный набор сильных invariants и gates с доказанным
> signal, owner, applicability и adversarial evidence.
