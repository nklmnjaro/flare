---
title: "Flare — Engineering Standard"
document_id: "FLARE-ENGINEERING-STANDARD-0001"
version: "1.0"
status: "PROPOSED AUTHORITATIVE"
owner: "Product Owner / Main Coordinator"
language: "ru"
date: "2026-08-07"
applies_to:
  - Product Owner
  - Analyst
  - Go Backend
  - Frontend
  - QA №1 Protocol/API/Reliability
  - QA №2 Product E2E/Browser
  - Platform/DevOps
  - Linter/Quality Tooling
  - Gatekeepers
  - Future contributors
---

# Flare — единый инженерный стандарт

## 0. Зачем этот документ

Это не памятка и не пожелание.

Это кандидат на **единый authoritative инженерный стандарт Flare**, который должен
заменить дублирование одинаковых законов по role-specific регламентам.

Его цель:

> **решать реальные проблемы минимальным доказуемым изменением и после каждого
> изменения оставлять Flare строже, проще, безопаснее и понятнее следующему
> инженеру.**

Команда не оптимизируется на:

- количество написанного кода;
- количество сервисов;
- количество тестов;
- количество линтеров;
- количество PR;
- 100% coverage ради цифры;
- модность стека;
- скорость закрытия Jira любой ценой.

Команда оптимизируется на:

- корректность;
- продуктовую ценность;
- простоту;
- доказательства;
- устойчивые контракты;
- bounded failure behavior;
- безопасность;
- воспроизводимость;
- диагностируемость;
- скорость понимания системы новым инженером.

---

# 1. Главный закон: инженер не является генератором кода

Любая задача, решение, ADR, existing code, указание Product Owner,
аналитика, Gatekeeper — **гипотеза до проверки**.

Перед реализацией исполнитель обязан проверить:

```text
Problem действительно существует?
Есть evidence?
Есть пользовательская/операционная ценность?
Current behavior подтверждено?
Решение вообще требует кода?
Есть более простое решение?
Scope минимален?
Контракт определён?
Failure modes известны?
Security impact известен?
Observability достаточна?
Timeout/cancellation/backpressure определены?
Rollback/migration понятны?
Acceptance criteria исполняемы?
Owner известен?
```

Если существенная предпосылка не выдерживает проверки, код не пишется.

Допустимые verdict:

```text
TASK ASSUMPTION INVALID
SCOPE CORRECTION REQUIRED
SIMPLER SOLUTION PROPOSED
INSUFFICIENT EVIDENCE
PRODUCT DECISION REQUIRED
DO NOT IMPLEMENT
```

Возражение обязано содержать:

```text
Assumption
Evidence
Risk
Simpler alternative
Required decision
Verification plan
```

Слепое исполнение слабой постановки считается инженерным дефектом.

---

# 2. Evidence важнее должности

При конфликте использовать порядок:

```text
1. подтверждённый Product Decision / product contract;
2. versioned protocol/API/storage/security contract;
3. воспроизводимый runtime evidence;
4. strict automated contract/architecture/integration tests;
5. актуальный source code;
6. ADR/RFC/runbook/docs;
7. текст задачи;
8. историческая договорённость или мнение.
```

Важно:

- код может нарушать контракт;
- тест может закреплять старый дефект;
- документация может устареть;
- Product Owner определяет value и scope, но не может объявить технический факт
  истинным без evidence;
- Gatekeeper также может ошибаться.

Техническое несогласие разрешается доказательствами.

---

# 3. Smallest Correct Change

Базовая форма изменения:

```text
одна подтверждённая проблема
→ минимальное достаточное решение
→ автоматическая защита
→ воспроизводимое evidence
→ понятный rollback
```

Запрещено без отдельного обоснования:

- "заодно" переписывать соседние модули;
- feature + большой refactor + dependency upgrade в одном change set;
- generic framework для двух случаев;
- новый deployable "на будущее";
- abstraction без реальной вариативности;
- интерфейс для каждой структуры;
- DI-container ради красивой схемы;
- broker/cache/database без измеренного use case;
- DTO/event/status только ради одного компонента UI.

Перед merge крупного изменения обязательно спросить:

```text
Можно удалить abstraction?
Можно удалить dependency?
Можно избежать нового service?
Можно избежать queue?
Можно избежать дополнительного состояния?
Можно решить это стандартной библиотекой?
```

Если да — решение упрощается.

---

# 4. MVP simplicity guardrails

До отдельного evidence-backed решения Flare MVP сохраняет простую топологию:

```text
flare-server       Go modular monolith
flare-web          SolidJS frontend
flare-pytest       Python pytest SDK/plugin
PostgreSQL
S3-compatible object storage
```

Go Core владеет canonical accepted facts, lifecycle, durability, replay и
минимальными projections.

Прямой realtime path:

```text
browser ← SSE ← Go Core
```

До доказанной продуктовой необходимости **не вводить**:

```text
Python Feature Plane runtime
Redis
Kafka / NATS
ClickHouse / Big Data runtime
generic event-sourcing framework
adaptive rolling capture
persisted Evidence Graph
Execution Capsule engine
interactive debugger/control plane
AI critical path
```

Расширяемость создаётся устойчивыми контрактами и boundaries, а не заранее
созданными сервисами.

---

# 5. Непереговорные runtime invariants

До production-реализации соответствующего пути должны быть определены и проверяемы:

1. At-least-once delivery + idempotent ingestion.
2. Нет предположения о global ordering.
3. `producer_id + sequence` — producer ordering; не browser replay cursor.
4. Durable acceptance имеет точное определение.
5. SSE использует server-issued durable cursor.
6. Reconnect либо replay-ит, либо явно требует resync.
7. Slow client никогда не блокирует ingest.
8. Каждая queue/buffer/pool bounded.
9. Каждый retry имеет deadline, budget, backoff и cancellation.
10. Каждая goroutine/background worker имеет owner и shutdown.
11. Reporter failure не меняет pytest outcome.
12. Reporter degradation — first-class observable state.
13. Evidence Completeness не может быть COMPLETE после известной потери evidence.
14. Producer-side и server-side redaction происходят до persistence sensitive data.
15. Accepted canonical events не переписываются молча.
16. Projections rebuildable/restartable без generic ES framework.
17. Mandatory evidence ack не зависит от browser delivery.
18. External calls имеют timeout и классифицированную ошибку.
19. Attachment/log/resource limits конечны.
20. Dogfooding Flare не является единственным oracle корректности Flare.

---

# 6. Evidence classification вместо преждевременной Capture Platform

Для MVP достаточно простой классификации:

```text
MANDATORY
OPTIONAL
BINARY
SENSITIVE / PROHIBITED
```

Для каждого класса определяются:

```text
можно ли принимать;
где redaction;
size limit;
durability expectation;
overflow/drop behavior;
retention;
user-visible completeness impact.
```

Не вводить LIGHT/STANDARD/DEEP/DEBUG profiles до measurements реальных sessions.

---

# 7. Quality Ratchet — найденная слабость становится защитой

Это центральный закон проекта.

```text
Found weakness
→ reproduce
→ classify root cause
→ fix
→ add regression
→ move detection earlier
→ test the guard adversarially
→ document the invariant
```

Исправить только конкретную строку недостаточно.

Примеры:

```text
secret leak
→ regression + redaction rule + scanner where practical

invalid dependency direction
→ architecture/import gate

duplicate event bug
→ idempotency/contract integration test

flaky sleep
→ deterministic waiter + anti-sleep rule

stale baseline metadata
→ metadata validator + negative mutation

invalid CI graph
→ CI contract test

manual DTO copy
→ generated drift check

reviewer повторно ловит timeout
→ static/architecture gate, если detection реалистичен
```

Предпочитаемый уровень защиты:

```text
compiler/type system
→ generated contract/breaking checker
→ static/architecture gate
→ unit/property/fuzz
→ integration
→ E2E
→ human review
```

Human review не заменяет автоматизируемый gate.

---

# 8. Gate Hardening Protocol

Сам quality gate считается production code.

Custom validator / checker обязан иметь:

```text
positive case
negative case
malformed input
missing required data
unknown value
duplicate identifier
stale reference/baseline
invalid dependency
deterministic output
correct exit codes
```

Обязательно:

```text
намеренно сломали fixture/config/source
→ gate обязан стать RED
```

Gate, проверенный только на зелёном проекте, не считается доказанным.

---

# 9. Запрет ослабления качества ради зелёного CI

Нельзя без отдельного доказанного exception:

```text
удалять assertion;
fail → warning;
добавлять permanent skip;
retry until green;
добавлять sleep;
увеличивать timeout без измерения;
добавлять Any/any;
расширять ignore/exclude;
отключать type/architecture/security gate;
понижать coverage critical logic;
добавлять broad noqa/nolint/type-ignore;
маскировать product bug как expected behavior.
```

Если gate плох:

1. воспроизвести false positive/false negative;
2. доказать дефект gate;
3. написать regression самого gate;
4. минимально исправить правило;
5. прогнать affected full lane.

Exception обязан содержать:

```text
reason
scope
risk
owner
issue
expiry/review date
compensating control
removal condition
```

Глобальное suppression ради одного случая запрещено.

---

# 10. Zero-noise target

Blocking lanes стремятся к:

```text
0 unexplained warnings
0 permanent skips
0 silent retries
0 ignored errors
0 unowned suppressions
0 TODO without issue
0 hidden failed checks
0 raw secret leaks
```

Warning нельзя "просто оставить". Он либо исправляется, либо доказан как false
positive и подавляется максимально локально.

---

# 11. Минимальный quality baseline

Инструменты добавляются не ради количества. У каждого должен быть конкретный
класс риска и owner.

## Go

```text
gofmt
goimports
go vet
staticcheck
golangci-lint        # только полезные complementary rules
govulncheck
go test
go test -race
```

Плюс по риску:

```text
architecture/import tests
migration tests
fuzz
benchmarks
repository integration tests
```

## Python / pytest SDK / QA

```text
Ruff format --check
Ruff check
mypy --strict
Pylint               # только complementary checks
Import Linter
pytest architecture
pytest unit
pytest contract
pytest integration where applicable
pytest collection validation
coverage branch ratchet
pre-commit
dependency/security audit
```

## TypeScript / SolidJS

```text
Biome
tsc --noEmit with strict flags
architecture/dependency check
dead-code check
Vitest
Testing Library / browser component tests
Playwright Chromium
accessibility checks
generated-contract drift
production build
bundle budget
dependency/security audit
```

Firefox/WebKit не являются blocking scope MVP без отдельного решения.

## Contracts

```text
buf format
buf lint
buf breaking
generated drift check
golden/round-trip tests
cross-language compatibility
enum/state exhaustiveness
```

Ручное дублирование DTO Go/Python/TypeScript запрещено.

## Platform / CI / containers

По применимости:

```text
shfmt
ShellCheck
actionlint
GitHub Actions security analysis
Hadolint
YAML/schema validation
helm lint
helm template
kubeconform
Trivy
SBOM generation
Cosign/signing or attestation at release maturity
CI contract tests
artifact path/ownership tests
reproducibility checks
```

Главная логика живёт в:

```text
Makefile / project CLI / tested scripts
```

GitHub Actions и GitLab CI — тонкие adapters.

## Documentation

Минимум:

```text
broken links
frontmatter/schema where defined
document ID uniqueness
ADR/reference integrity
Mermaid validation where practical
stale authoritative reference detection
```

---

# 12. Strict code boundaries

## Go

Автоматически запрещать, где это даёт качественный сигнал:

```text
domain → transport/adapter implementation
generated DTO inside domain
mutable package globals
ignored errors
log.Fatal/os.Exit outside main
unowned goroutine
unbounded channel
production polling via time.Sleep
HTTP client without timeout
raw env access outside config boundary
raw SQL outside storage adapter
secret logging
```

## Python

```text
Any outside validated dynamic boundary
raw dict after parsing boundary
network I/O in pytest hooks
domain importing pytest/HTTP/Allure
unbounded queue
retry without deadline
while True without proven lifecycle
sleep-based synchronization
business logic in tests/conftest
secret attachment/log
environment access outside config boundary
```

## Frontend

```text
any
unchecked external payload
manual transport DTO copy
backend state machine duplicated in UI
feature private deep imports
arbitrary fetch from presentation component
unowned SSE subscription
unbounded reconnect/cache/DOM
silent unknown-status fallback
floating promises
raw HTML/sensitive attachment execution
color-only critical status
waitForTimeout in E2E
```

---

# 13. Complexity limits

Ориентиры:

```text
function soft limit: 60 lines
function hard limit: 100 lines
arguments soft limit: 5
arguments hard limit: 8
```

Hard limit — не автоматический приговор, но требует явного justification.

Запрещено бессмысленно дробить cohesive logic ради счётчика.

Содержательные названия обязательны. Мусорные buckets:

```text
utils
helpers
common
misc
manager
service
base
core
```

не допускаются без чёткой ответственности.

---

# 14. Test engineering

Разработчик сам доказывает корректность компонента.
QA независимо доказывает контракт и продукт.

Каждый тест имеет одного primary owner.

## QA №1

Владеет независимыми доказательствами:

```text
pytest plugin / SDK
protocol/API
ordering/idempotency/dedup
PostgreSQL/object storage boundaries
spool/recovery
restarts/partial failures
security/redaction
load/reliability
```

## QA №2

Владеет:

```text
real user journeys
pytest → backend → live UI
reconnect/refresh
degraded/incomplete states
Chromium E2E
accessibility
UI performance/memory
demo/release product acceptance
```

## Разработчики

Backend/Frontend/Platform сами владеют component/unit/integration/contract tests
своего implementation.

### Запрещено

```text
retry-driven green CI
sleep-driven synchronization
permanent skip
mock-only "E2E"
слабые assertions ради стабильности
test order dependency
production algorithm duplicated inside test oracle
```

Flaky test = defect.

---

# 15. Coverage policy

Coverage — ratchet, не KPI.

Особенно строгие области:

```text
protocol validation
state machines
security/redaction
ordering/idempotency
recovery
lifecycle
migration
permission boundaries
```

Для critical logic требуется высокий branch coverage и negative scenarios.

Снижение baseline требует отдельного evidence-backed решения.

Mutation testing вводится позже только для critical logic, если оно даёт
дополнительный сигнал.

---

# 16. Performance и ресурсы

Запрещены claims:

```text
fast
scalable
low-overhead
memory-efficient
production-ready
```

без measurement artifact.

Benchmark содержит:

```text
baseline
candidate
reference dataset
environment fingerprint
exact command
iterations
p50/p95/p99 where meaningful
CPU
memory
variance
limitations
```

Performance thresholds не придумываются до baseline.

Для каждого runtime buffer:

```text
owner
capacity
overflow behavior
deadline/cancellation
metric
shutdown
user-visible degradation semantics
```

Unbounded resource блокирует merge.

---

# 17. Security

Security — blocking gate.

External boundary обязана иметь по применимости:

```text
validation
size limit
timeout
authentication/authorization
secret handling
negative tests
security-safe structured logs
```

Evidence:

- redaction producer-side;
- redaction server-side;
- запрещённые secret classes;
- attachment size/content validation;
- checksum;
- safe filenames/storage keys;
- no executable raw HTML;
- archive/path traversal protection;
- retention;
- auditability where needed.

Любой secret leak блокирует merge и требует regression + ratchet.

---

# 18. Dependency policy

Новая dependency обязана доказать:

```text
Problem solved
Why stdlib/current stack is insufficient
Maintenance activity
Release policy
License
Security history
API stability
Transitive dependency cost
Binary/bundle/startup impact
Removal cost
```

"Популярная", "современная", "может пригодиться" — не аргументы.

Lock/manifest является частью change set.

Удаление dependency приветствуется.

---

# 19. CI и Platform — production code

Local/CI workflow должен иметь один source of truth.

Целевой интерфейс:

```text
make doctor
make bootstrap
make check-fast
make check
make dev
```

или эквивалентный единый project CLI.

Pipeline providers вызывают эти команды, а не реализуют их заново.

`doctor` read-only.

`bootstrap`:

- идемпотентный;
- version-aware;
- не ломает существующее окружение;
- устанавливает/подсказывает missing dependencies;
- использует lock/manifest;
- не содержит hidden steps;
- имеет regression tests.

Local platform развивается:

```text
Docker Compose
→ Minikube для Kubernetes-specific behavior
→ real Kubernetes
```

Не поддерживать несколько локальных Kubernetes ради количества.

---

# 20. Documentation as executable knowledge

Критичное знание не остаётся в чате.

После решения/incident/review:

```text
chat knowledge
→ contract / ADR / test / gate / runbook / onboarding
→ repository
```

Документация считается дефектной, если команда из неё не работает.

Документы не должны дублировать один и тот же закон. Этот стандарт становится
authoritative; role-specific документы сохраняют только действительно
role-specific детали и ссылаются сюда.

---

# 21. Onboarding — часть качества продукта

`bus factor = 1` считается инженерным дефектом.

Должен существовать один entry point:

```text
docs/onboarding/START-HERE.md
```

Он отвечает:

```text
что такое Flare;
MVP promise;
архитектура;
current baseline/iteration;
ownership;
repository map;
contracts;
bootstrap;
check-fast/full;
reference flow;
debugging;
known limitations;
ADR/decision index;
runbooks;
как challenge-ить задачу;
как делать handoff.
```

## Первые 30 минут

Новый инженер должен:

```text
прочитать START-HERE;
понять свой scope;
найти current baseline;
запустить doctor;
найти fast gates.
```

## Первые 2 часа

Без устной магии:

```text
bootstrap
check-fast
минимальный local stack
reference flow
один controlled failure
поиск evidence
```

## Первый день

Инженер обязан:

- пройти data flow своей области;
- найти contracts/owners;
- воспроизвести failure/recovery scenario;
- сделать небольшое настоящее изменение;
- увидеть ожидаемый RED от намеренного нарушения одного quality gate;
- вернуть корректный handoff.

Если это невозможно без старожила — onboarding failed, и это defect проекта.

## Fresh-machine test

Onboarding периодически проверяется из чистой/ephemeral среды:

```text
clean environment
→ bootstrap
→ check-fast
→ minimal integration/reference flow
```

---

# 22. Continuity / replacement protocol

Если любой worker исчезает сегодня, проект не должен останавливаться.

Для критичной области должны быть:

```text
owner
review-capable backup
current baseline
active task
accepted/open decisions
contracts
known defects
tests
runbook
quality status
next safe action
artifact/checksum
```

Replacement worker не должен зависеть от:

```text
private chat history
личного shell history
uncommitted local files
скрытого .env
устной легенды
```

Незавершённый код предыдущего worker считается untrusted candidate и заново
проходит task challenge.

---

# 23. Handoff

В чат:

```text
STATUS
decision/verdict
blockers
checks
artifact link
```

Объёмная работа — файлом/архивом.

Каждый handoff содержит:

```text
Role
Task ID
Baseline SHA
Task assumptions reviewed
Rejected assumptions
Scope corrections
Simplifications proposed
Scope completed / not completed
Files changed/deleted
Contract impact
Migration impact
Security impact
Performance impact
Checks run + exact result
Checks not run + reason/risk
Known failures
Product defects
Suppressions introduced
Shared-file conflicts
Integration order
Rollback
Artifact SHA-256
```

Фраза `all checks passed` без команд и результата запрещена.

---

# 24. Definition of Ready

Production implementation не начинается без:

```text
confirmed problem
user/outcome
evidence
acceptance criteria
invariants
forbidden behavior
failure scenarios
contract impact
security impact
observability
dependencies
owner
scope/non-goals
migration/rollback where applicable
measurable success
```

Если этого нет — задача возвращается, а не додумывается worker-ом молча.

---

# 25. Definition of Done

Change не Done пока применимые пункты не доказаны:

```text
implementation complete
format green
lint green
typing green
architecture green
contract green
unit green
integration/E2E where applicable green
race/concurrency where applicable green
security green
dependency checks green
generated code synchronized
migration/rollback verified where applicable
observability updated
docs updated
no unexplained warnings
no permanent skips
no unowned suppressions
performance budget proven where affected
regression protection added
handoff reproducible
```

`Код написан` != Done.

---

# 26. AI-assisted development

Сгенерированный AI-код рассматривается как код нового неизвестного сотрудника.

Он не принимается потому, что:

```text
компилируется;
выглядит идиоматично;
имеет много тестов;
написан сильной моделью.
```

Автор change set обязан:

```text
понимать каждую нетривиальную часть;
защитить архитектуру;
объяснить failure modes;
доказать security;
объяснить dependencies;
показать tests/evidence;
быть готовым удалить решение.
```

Если автор не может объяснить код — код не готов.

---

# 27. Обязательная культура несогласия

Хорошее поведение:

- остановить плохую задачу;
- доказать неверный acceptance;
- предложить меньше кода;
- отказаться от ненужной зависимости;
- потребовать benchmark;
- потребовать failure test;
- потребовать rollback;
- удалить преждевременную abstraction;
- вернуть PR несмотря на "почти зелёный" pipeline.

Плохое поведение:

- молча выполнить спорное решение;
- согласиться ради скорости;
- спрятать warning;
- оставить bypass "потом";
- принять код, который никто не способен объяснить;
- не сообщить о соседнем существенном риске.

---

# 28. ОБЯЗАТЕЛЬНЫЙ review самого этого стандарта

Этот документ **не является непогрешимым**.

После получения его версии `1.0` каждая роль обязана провести независимый
challenge review и не менее строго проверить сам регламент.

Нельзя отвечать:

```text
"согласен"
"выглядит хорошо"
"берём"
```

без анализа.

Каждая роль возвращает краткий artifact:

```text
Role
Verdict
Что оставить
Что удалить как лишнее
Что упростить
Что усилить
Какой rule конфликтует с реальным stack/contract
Какой rule невозможно честно автоматизировать
Какой новый gate действительно нужен
Какой gate будет лишним/дублирующим
Какие false-positive риски есть
Какие product decisions требуются
Предлагаемая редакция
Verification plan
```

Разрешённые verdict:

```text
APPROVE
APPROVE AFTER AMEND
REQUEST CHANGES
SCOPE CORRECTION REQUIRED
DO NOT ADOPT
PRODUCT DECISION REQUIRED
INSUFFICIENT EVIDENCE
```

## Главное требование к review

Роль обязана **самостоятельно принять инженерное решение в сторону улучшения**.

Если правило:

- слишком сложное — упростить;
- дублируется — удалить;
- слабое — усилить;
- невозможно надёжно автоматизировать — не притворяться gate;
- создаёт false positives — переработать;
- конфликтует с продуктовым контрактом — вернуть на решение;
- защищает реальный риск — оставить и доказать.

Никто не должен сохранять плохое правило только потому, что его написал
аналитик, Gatekeeper или координатор.

После независимых review:

```text
role reviews
→ Analyst consolidates conflicts
→ Gatekeepers challenge consolidation
→ Product Owner принимает только product/scope decisions
→ Quality owner кодирует автоматизируемые invariants
→ standard становится MANDATORY
```

---

# 29. Что должно получиться после принятия

Не "больше линтеров".

Должно стать меньше:

- повторяющихся дефектов;
- ручных review comments;
- flaky;
- tribal knowledge;
- скрытых assumptions;
- duplicated CI logic;
- неопределённых contracts;
- бессмысленных dependencies;
- времени onboarding;
- случайного scope.

И больше:

- ранних дешёвых failures;
- executable architecture;
- deterministic tests;
- meaningful evidence;
- понятных boundaries;
- воспроизводимых environments;
- правильных возражений;
- возможности удалить сложность.

---

# 30. Финальный договор

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

Три финальных правила:

> **Не пиши код, пока не доказал, зачем он нужен.**

> **Если слабость можно запретить машиной — не оставляй её на совесть reviewer.**

> **Если более простое решение даёт те же гарантии — сложное решение отклоняется.**
