# START HERE

## Product

Flare is a test-execution observability and investigation platform.

MVP:

> show a live pytest session and preserve trustworthy evidence.

## Current architecture boundary

```text
flare-pytest
  ↓
Go flare-server
  ↓
PostgreSQL + S3-compatible storage
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

## Engineering law

Read:

```text
docs/engineering/ENGINEERING_STANDARD.md
```

Before implementation:

```text
Criticize → Prove → Simplify → Implement → Verify → Harden
```

## Current production authorization

Production implementation must remain blocked until the accepted FLARE-000
baseline explicitly authorizes it.
