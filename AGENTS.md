# Flare — Codex project instructions

Keep this file small. Authoritative semantics live in repository contracts and
decisions, not in agent memory.

## Before changing code

1. Derive the exact Git HEAD and working-tree status.
2. Read the accepted Change / Iteration Contract for the task.
3. Read applicable authoritative decisions and repository guidance.
4. Challenge the task before implementation.
5. If a material assumption, contract, ownership or scope claim is wrong, stop
   the affected work and report one of:

```text
TASK ASSUMPTION INVALID
SCOPE CORRECTION REQUIRED
SIMPLER SOLUTION PROPOSED
INSUFFICIENT EVIDENCE
PRODUCT DECISION REQUIRED
DO NOT IMPLEMENT
```

Do not treat authority as evidence.

## Current durable coordination boundary

When `docs/project/state.json` exists, treat it only as the canonical current
coordination index and resolve its referenced authoritative sources.

Do not put normative product/protocol/security/architecture prose into project
state.

Do not persist transient Codex runtime state in Flare coordination state.

## Production boundary

Production/product runtime remains frozen until an explicit authoritative:

```text
APPROVE FLARE-000
```

Never infer production authorization from implementation authorization.

## Execution boundary

Flare owns engineering semantics.
Codex owns execution mechanics.

Read:

`docs/adr/FLARE-ADR-CODEX-EXECUTION-BOUNDARY.md`

Do not implement custom agent orchestration unless a separate accepted Change
proves a concrete missing Codex/runtime capability.

Default to one agent.

Delegate only bounded independent work when it materially improves speed,
quality, or context isolation. Prefer subagents for read-heavy exploration,
verification, triage and independent review. Avoid overlapping parallel writes.

## Engineering discipline

Use this priority when choosing among correct designs:

```text
DRY → KISS → SOLID → YAGNI
```

DRY means removing duplicated knowledge/contracts, not mechanically deleting
similar lines.

Prefer native language/platform protocols and mature dependencies when they
reduce code and risk.

Do not weaken checks to obtain green.

A defect fix should receive a regression/guardrail when applicable.

## Verification

During implementation, run the narrowest meaningful applicable checks while
context is hot.

Before declaring a Change ready, run the canonical applicable fast verification
surface (`make check-fast`) when the repository supports it.

Do not dump large successful logs into agent context. Summarize PASS results.
For RED, surface the bounded relevant failure and preserve larger evidence as an
artifact if needed.

Agent claims such as `PASS` are not authority. Evidence is the exact command,
exit code, result and Git diff/commit where applicable.

## Git / handoff

Prefer Git-native handoff when repository access is shared:

```text
baseline commit
→ result commit
→ verification evidence
```

Public history should explain logical engineering decisions.

Do not create separate public commits such as `fix linters` for corrections that
belong to the same logical Change. Amend/fixup/autosquash before integration
when appropriate.

Do not force unrelated independently revertible work into one commit merely for
one-commit aesthetics.

## Required completion summary

Return concise sections:

```text
Task assumptions reviewed
Rejected assumptions
Scope corrections
Simplifications proposed
Product decisions required
Changed files
Checks
Evidence
Known blockers / follow-ups
```

Empty sections are allowed when explicitly `None`.
