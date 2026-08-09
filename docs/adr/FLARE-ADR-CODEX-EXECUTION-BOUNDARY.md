# Flare ADR — Codex Execution Boundary

**Status:** `ACCEPTED FOR EXPERIMENT`
**Workflow standardization:** `NOT YET STANDARDIZED`
**Date:** `2026-08-08`

## Decision

```text
Flare owns engineering semantics.
Codex owns execution mechanics.
```

Flare repository owns durable and vendor-neutral engineering truth:

- product and technical decisions;
- accepted Change / Iteration Contracts;
- ownership;
- quality and verification policy;
- durable coordination state;
- accepted Git/evidence boundaries.

Codex may provide current execution mechanics:

- agent and subagent lifecycle;
- threads;
- transient context;
- parallel execution;
- isolated working copies / worktrees where supported;
- temporary execution state.

Codex is an execution adapter, not a contract authority.

## Hard non-goals

Do not implement without a separate evidence-backed Change:

```text
Flare agent scheduler
Flare subagent manager
Flare worktree manager
Flare agent runtime database
Flare thread registry
Flare context router
Flare agent message bus
generic workflow engine
```

## Canonical-state boundary

Durable Flare coordination state MUST NOT require or persist:

```text
Codex thread IDs
Codex subagent IDs
Codex worktree paths
agent heartbeat/status
queued prompts
agent parent/child runtime graph
transient context identifiers
```

If Codex disappears, another engineer or execution runtime must still be able to
recover Flare from repository-owned state and contracts.

## Vendor-neutral contract rule

Normative Flare contracts describe required capabilities, for example:

```text
perform independent read-only review
use an isolated working copy for parallel write work
return structured verification evidence
```

They do not normatively require:

```text
spawn Codex subagent
open Codex worktree
handoff Codex thread
```

Codex-specific `AGENTS.md`, Skills and `.codex/agents/*.toml` are thin execution
adapters only.

## Agent-profile policy

Project-scoped Codex role agents are experimental reusable execution profiles.

They are not:

```text
durable project memory
new permanent team roles
canonical owners
authorities over Flare contracts
```

Default execution is one agent.

Use subagents only when work is genuinely decomposable, especially for:

- read-heavy exploration;
- independent review;
- test/failure triage;
- bounded evidence gathering.

Be conservative with overlapping parallel writes.

## Verification boundary

Agent claims are untrusted until backed by reviewable evidence.

Preferred evidence:

```text
exact Git diff/commit
exact command
exit code
bounded result
canonical independent checks
```

Agent self-check is useful feedback.
CI remains integration authority where applicable.

## Benchmark requirement

Codex-native workflow is experimental until measured against the current flow.

Evaluate at least these task shapes:

```text
Local bounded change
Read-heavy investigation
Boundary change + independent review
```

Measure the whole agent tree, including:

- model/token cost;
- human active effort;
- wall-clock;
- context reloads/repeated reads;
- failed handoffs;
- post-handoff RED;
- review findings;
- integration/conflict effort;
- final history cleanliness.

Recommendation requires non-inferior correctness/reproducibility and a material
cost benefit in at least one major dimension without unacceptable regressions.

A hybrid result by task class is explicitly acceptable.
