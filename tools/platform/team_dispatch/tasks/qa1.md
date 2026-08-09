# QA1 Protocol / API / Reliability

Role: `kolyan_qa`
Timing: `ACT_NOW`
Source: `${source_commit}`
Baseline SHA-256: `${baseline_sha256}`

## Goal
Prove protocol/API/reliability facts without inventing semantics. Observed pytest
facts are not automatically Flare durable-ACK, ordering or producer-incarnation
contracts.

## TASK PREFLIGHT
Verify packet checksums, baseline, governance and actual source. No skips,
flaky masking, fixed sleeps or weakened assertions.

Production freeze: `${production_freeze}` until explicit `APPROVE FLARE-000`.
