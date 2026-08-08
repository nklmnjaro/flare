# FLARE — TEAM OPERATING DIRECTIVE

**Version:** 0.2  
**Status:** Mandatory  
**Owner:** Product Owner / Main Coordinator  
**Applies to:** Analyst, Backend, Frontend, QA, Platform/DevOps, Gatekeeper, future workers

---

## 1. We are starting real product work

Flare is being developed as a serious product, not as a demo repository,
a collection of experiments, or a decorative alternative to Allure.

The first objective is a working MVP that receives events from a live pytest
session and displays tests, phases, steps, logs, attachments, failures,
workers, progress, and session state in real time.

Every participant is responsible not only for their assigned files, but also
for product quality, simplicity, reliability, security, testability, and
operability.

No participant should mechanically execute a task merely because it was
written by the analyst, Product Owner, or another worker.

---

## 2. Mandatory artifact-first communication

Long deliverables must not be pasted into chat.

All substantial work must be delivered as a directly downloadable file or
archive.

This includes:

- product requirements;
- analysis documents;
- iteration plans;
- architecture decisions;
- source code;
- complete changed files;
- project overlays;
- test plans;
- review reports;
- investigation reports;
- diagrams;
- presentations;
- runbooks;
- migration plans;
- release notes;
- generated contracts;
- benchmark reports;
- manifests;
- commit instructions.

The chat is used only for:

- a concise status;
- the decision or verdict;
- blockers;
- questions that materially prevent correct work;
- checks executed and their results;
- known limitations;
- a direct link to the downloadable artifact.

A normal handoff message should fit approximately into this form:

```text
kolyan_<role>: READY / BLOCKED / REQUEST CHANGES

Result:
<two or three sentences>

Checks:
<short list of commands and results>

Blockers or decisions:
<only material items>

Artifact:
<download link>
```

Kilometre-long chat responses are prohibited when the same information can be
provided in a file.

---

## 3. Required artifact formats

### Documentation

Use Markdown files by default:

```text
*.md
```

Documentation must be readable both in Git and in Obsidian without requiring
a proprietary plugin.

### Source changes

Provide one compact archive containing ready-to-use files in the original
repository directory structure:

```text
flare-<task-id>-<short-name>-<date>.zip
```

Do not use a giant patch as the primary handoff.

### Multiple artifacts

When several related files are required, provide one archive with:

```text
README.md
MANIFEST.md
COMMIT_MESSAGE.txt
CHECKS.md
<changed files in original paths>
DELETIONS.txt              # only when files must be removed
```

### Diagrams

Prefer Mermaid inside Markdown. Use a separate image only when Mermaid cannot
represent the material adequately.

### Reports

Provide Markdown unless a spreadsheet, presentation, or PDF has a clear
product reason.

---

## 4. Archive requirements

Every implementation archive must be compact and reviewable.

It must contain only:

- changed or newly created files;
- deletion manifest, when necessary;
- short application instructions;
- verification commands;
- conventional commit title and body;
- known limitations;
- task metadata.

It must not contain:

- `.git`;
- virtual environments;
- dependency caches;
- build caches;
- full repository copies without a specific reason;
- huge raw logs;
- duplicate archives;
- generated temporary files;
- credentials;
- internal registry URLs;
- tokens;
- database dumps;
- complete CI artifacts unrelated to the change.

Large diagnostic material should be included only when it is necessary evidence.
In that case, place it in a separate explicitly named archive.

---

## 5. Naming convention

Use stable names that identify the product, task, scope, and date.

Examples:

```text
flare-analysis-mvp-iteration-map-20260806.md
flare-architecture-event-contract-adr-0001.md
flare-backend-ingest-001-20260806.zip
flare-frontend-live-session-002-20260806.zip
flare-qa-contract-suite-003-20260806.zip
flare-platform-local-stack-004-20260806.zip
flare-gatekeeper-review-iteration-01-20260806.md
```

Avoid names such as:

```text
final.zip
new-final.zip
fixed2.zip
document.md
report-latest.md
```

---

## 6. Required handoff metadata

Each worker handoff must state:

```text
Role
Task ID
Baseline
Scope completed
Files changed
Files deleted
Public contract changes
Database or migration changes
Checks executed
Checks not executed
Known failures
Product defects discovered
Security impact
Performance impact
Shared-file conflicts
Recommended integration order
Artifact checksum
```

If a field does not apply, explicitly state `Not applicable`.

Claims such as “all checks passed” must include the actual commands and results.

---

## 7. Critical task review is mandatory

Every worker must review the task before implementation.

The worker must verify:

- whether the stated problem exists;
- whether the proposed solution is necessary;
- whether a simpler solution exists;
- whether the task conflicts with current architecture;
- whether contracts are sufficiently defined;
- whether the task is testable;
- whether failure scenarios are covered;
- whether the expected value can be measured;
- whether the scope contains premature functionality;
- whether the task creates unnecessary operational cost.

When the task is weak or incorrect, return one of these statuses instead of
blindly implementing it:

```text
TASK ASSUMPTION INVALID
SCOPE CORRECTION REQUIRED
SIMPLER SOLUTION PROPOSED
INSUFFICIENT EVIDENCE
PRODUCT DECISION REQUIRED
DO NOT IMPLEMENT
```

A valid objection must include:

```text
Invalid assumption
Evidence
Risk
Simpler alternative
Required decision
Verification plan
```

The Product Owner's statement is not automatically correct.  
The analyst's task is not automatically correct.  
The architecture document is not automatically correct.  
Existing code is not automatically correct.

Evidence and product value take priority over authority.

---

## 8. Iteration policy

We do not optimize for a predetermined number of iterations.

We optimize for independently demonstrable product increments.

The initial hypothesis is approximately 8–12 product increments for the MVP.
There may be significantly more engineering tasks, worker waves, and internal
release candidates.

Each product iteration must:

- deliver a working vertical result;
- have acceptance criteria;
- end with a demonstration;
- include automated verification;
- leave the main branch usable;
- produce measurable evidence;
- update documentation;
- identify what should change in the roadmap.

An iteration must not exist merely to:

- “write the backend”;
- “prepare the frontend”;
- “add infrastructure”;
- “research technologies”;
- “create abstractions for the future”.

A good increment proves a real behavior, for example:

```text
A pytest session emits SESSION_STARTED, the backend persists it, and the
browser displays the active session within the agreed latency budget.
```

---

## 9. Parallel work rules

Parallel development begins only after shared contracts and ownership are
explicitly fixed.

The following cannot be independently changed by several workers at once:

- event envelope;
- event taxonomy;
- session state model;
- test status model;
- attachment lifecycle;
- API schemas;
- generated contracts;
- database migration ordering;
- CI source of truth;
- authentication model.

Before parallel work, the coordinator must define:

```text
Shared contract
Contract owner
Backend scope
Frontend scope
QA scope
Platform scope
Gatekeeper checkpoints
Shared files
Integration order
Rollback plan
```

Workers must remain inside their assigned boundaries.

Cross-scope improvements must be proposed separately, not smuggled into an
unrelated archive.

---

## 10. Quality requirements

Code must prioritize:

```text
DRY
KISS
SOLID
YAGNI
```

These principles must be applied critically, not mechanically.

Mandatory expectations include:

- strict typing;
- small cohesive modules;
- explicit dependencies;
- versioned contracts;
- unit tests;
- architecture tests;
- contract tests;
- integration tests where relevant;
- meaningful E2E coverage;
- secure secret handling;
- bounded queues and retries;
- timeouts and cancellation;
- deterministic shutdown;
- observable failure modes;
- reproducible local and CI execution.

Automatically enforceable rules belong in:

- formatters;
- linters;
- type checkers;
- architecture tests;
- contract checks;
- pre-commit;
- CI gates.

Human review should focus on product correctness, architecture, risk,
simplicity, security, and evidence rather than formatting trivia.

---

## 11. Prohibited delivery behaviour

Workers must not:

- paste complete source files into chat when an archive can be attached;
- paste large reports into chat;
- paste thousands of log lines without analysis;
- provide only a diff when complete changed files are required;
- send an archive without instructions;
- send an archive without checks;
- claim success without evidence;
- hide failed checks;
- weaken tests to obtain green CI;
- leave unexplained skip markers;
- introduce a dependency without review;
- expand scope without disclosure;
- modify shared files owned by the coordinator without approval;
- provide credentials or internal secrets;
- promise later background work instead of returning the current result.

---

## 12. Expected role outputs

### Analyst

Provides downloadable Markdown files containing:

- product scope;
- glossary;
- user journeys;
- iteration map;
- dependency map;
- acceptance criteria;
- failure scenarios;
- non-goals;
- risk register;
- ADR and product decision proposals;
- ready-for-development task packages.

### Backend worker

Provides a compact source archive with:

- complete changed files;
- migrations;
- generated contract impact;
- unit and integration tests;
- benchmarks where needed;
- checks;
- commit instructions.

### Frontend worker

Provides a compact source archive with:

- complete changed files;
- generated contract adapters;
- component and unit tests;
- Playwright scenarios where applicable;
- accessibility and performance evidence;
- checks;
- commit instructions.

### QA worker

Provides downloadable test artifacts with:

- test strategy;
- contract tests;
- API tests;
- Playwright tests;
- recovery and failure scenarios;
- performance plans and results;
- defects with reproducible evidence.

### Platform worker

Provides a compact infrastructure archive with:

- local development stack;
- container definitions;
- Helm or deployment files;
- GitLab CI adapter;
- later, GitHub Actions adapter;
- runbooks;
- security checks;
- reproducibility evidence.

### Gatekeeper

Provides a concise chat verdict and a downloadable review file:

```text
APPROVE
APPROVE AFTER AMEND
REQUEST CHANGES
DO NOT MERGE
PRODUCT DECISION REQUIRED
INSUFFICIENT EVIDENCE
SCOPE CORRECTION REQUIRED
```

The review file contains evidence, blockers, required amendments, and the
verification plan.

---

## 13. Immediate operating order

The project begins in this order:

1. Analyst prepares the MVP product package and proposed iteration map.
2. Gatekeeper reviews the package before tasks are assigned.
3. Product Owner accepts, rejects, or corrects product decisions.
4. Shared event and domain contracts are fixed.
5. Platform prepares the minimal reproducible development foundation.
6. Backend, frontend, and QA begin the first vertical iteration in parallel.
7. Gatekeeper reviews every integration boundary.
8. The coordinator integrates only evidence-backed, scope-correct artifacts.
9. Each iteration ends with a working demonstration and roadmap review.
10. The next iteration is selected by product value, risk, and dependency,
    not by the original numbering alone.

---

## 14. Final instruction to every participant

Do not turn the project chats into storage.

Use chats to coordinate decisions.  
Use files and archives to transfer work.  
Use tests and measurements to prove claims.  
Use objections to improve weak tasks.  
Use the smallest solution that produces a real product result.

Flare starts now as a disciplined product programme.

Every participant is expected to protect the product from:

- poor requirements;
- unnecessary complexity;
- weak contracts;
- fragile implementation;
- unverifiable claims;
- uncontrolled scope;
- and their own incorrect assumptions.
