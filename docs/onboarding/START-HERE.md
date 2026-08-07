<!-- flare-bootstrap-managed: v1 -->
# START HERE

## What is Flare?

Flare is a test-execution observability and investigation platform.

Current MVP promise:

> show a live pytest session and preserve trustworthy evidence.

## Current MVP topology

```text
flare-pytest
    ↓
flare-server (Go)
    ↓
PostgreSQL + S3-compatible object storage
    ↓
SSE
    ↓
flare-web
```

## First commands

```bash
make doctor
make check-fast
```

## Engineering standard

Read first:

```text
docs/engineering/ENGINEERING_STANDARD.md
```

Work model:

```text
Criticize
→ Prove
→ Simplify
→ Implement minimally
→ Verify independently
→ Harden the gate
```

Production implementation remains blocked until the accepted FLARE-000
baseline explicitly authorizes it.
