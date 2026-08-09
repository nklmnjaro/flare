---
change_id: "FLARE-EXECUTION-LOCAL-FIRST-001"
status: "ACCEPTED / READY FOR BOUNDED CODE"
implementation_authorization: "AUTHORIZED"
---

# Flare Local-First Execution Foundation

## Purpose

Make the repository sufficient to reconstruct and verify the supported local
development environment without hidden workstation state. Humans, Codex and
later CI must call the same project-owned engineering capabilities.

## Initial implementation scope

- Stage-0 host preflight/bootstrap boundary;
- read-only doctor;
- explicit idempotent bootstrap;
- small explicit project-owned command dispatcher;
- thin Makefile facade;
- `check-fast`, `check`, `verify` and `diagnose` commands containing only
  currently applicable capabilities;
- clean-checkout proof for a declared supported host profile;
- negative/adversarial doctor and bootstrap tests;
- exact tool version and provenance observability.

## Architecture constraints

Canonical execution semantics follow:

```text
tiny Stage-0 bootstrap/preflight
→ explicit tested project command modules
→ thin Makefile facade
→ humans / Codex / later CI adapters
```

This Change must not build a generic workflow engine, scheduler, retry engine,
dynamic DAG, plugin framework, Codex orchestration, agent/worktree manager or a
second CI implementation in YAML. Makefile must not own canonical tool flags or
policy.

## Bootstrap trust constraints

- no insecure TLS;
- no unverified downloads;
- checksum or digest verification when downloaded bytes are used;
- no mandatory private registry URL in portable source;
- no embedded credentials;
- no silent global toolchain mutation;
- no silent dependency-intent or lock mutation;
- an explicit supported host profile;
- repeat bootstrap is idempotent.

## Quality principle

Flare intentionally prefers a strong quality surface. Useful independent
linters and checkers may be introduced early as planned, advisory or diagnostic
capabilities and may run in parallel. Blocking promotion still requires a
useful and unique signal, intentional RED evidence, acceptable noise risk,
clear ownership, and applicable runtime and cost.

This Change does not implement the later Polyglot Quality Profile except for
checks already required by source that currently exists.

## Explicit non-goals

- Golden CI pipeline implementation;
- GitHub or GitLab adapters;
- candidate image promotion;
- full polyglot gate rollout for components that do not exist;
- report history, pages or notification platforms;
- product runtime;
- Poker integration;
- A.2 or A.3 implementation.

## Completion boundary

This Change ends when a clean supported checkout can reconstruct the local
environment and invoke the canonical project verification surface without
hidden workstation assumptions. Performance budgets require measurements and
are not specified by this activation contract.
