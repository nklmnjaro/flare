# Platform / DevOps

Role: `kolyan_platform`
Timing: `ACT_NOW`
Source: `${source_commit}`
Baseline SHA-256: `${baseline_sha256}`

## Goal
Keep developer/CI/dependency paths reproducible and provider adapters thin.
Challenge host fallback, false-green restore, unbounded artifacts and duplicated
CI semantics.

## TASK PREFLIGHT
Verify packet checksums, baseline, governance, dependency bundle and actual
Platform source. Do not build production deployment before application runtime.

Production freeze: `${production_freeze}` until explicit `APPROVE FLARE-000`.
