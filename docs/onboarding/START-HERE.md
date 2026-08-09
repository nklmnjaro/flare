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
make bootstrap
make doctor
make check-fast
```

The currently supported development host profile is declared in
`tools/local_execution/host_profile.toml`. Bootstrap reconstructs Python and
locked project dependencies under ignored project-local paths; it does not
install system packages or modify shell configuration.

The initial proven profile is Ubuntu 24.04 on x86_64. Its deliberately small
host trust root includes ordinary POSIX/OS tools plus the exact `uv` version
declared by that profile; Python and project dependencies are not taken from
`PATH` and are reconstructed locally. External package-source configuration is
accepted only through the variable names declared in the profile, while the
portable repository contains no private source or credentials. `make verify`
adds the expensive isolated twin-checkout reproducibility proof; HTML Allure
rendering remains optional and does not determine engineering-check status.

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
