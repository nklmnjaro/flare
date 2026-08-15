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
export FLARE_HOST_UV="$(command -v uv)"  # explicitly select your verified uv 0.12.3
make doctor
make bootstrap
make doctor
./flare install-hooks
make check-fast
make quality-advisory
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
The explicit hook installation writes only source-owned `/bin/sh` adapters in
this Git repository's common hooks directory, shared by linked worktrees, and
pins the repository-local `core.hooksPath` to that absolute directory. Each
invocation resolves its active checkout and re-enters that checkout's `./flare`
before any project Python can run. Canonical policy remains in `pyproject.toml`, `.gitlint`,
`tools/quality/ruff-lint.toml` and the project command implementation; hooks do
not copy those rules.

### Local execution trust boundary

The admission protocol detects persistent changes to the repository-owned
Python environment before Stage-1 execution. It also rejects unsafe filesystem
membership, poisoned process configuration and unadmitted direct adapters.
Stage-1 intentionally executes the admitted `.venv` without Python isolated
mode: its complete importable membership and interpreter identity have already
been sealed, launch holds the shared bootstrap lock, and the child receives a
minimal reconstructed environment. The direct project-interpreter reference in
the admission launcher is therefore the final admitted hop, not a fallback
around Stage-0.

This is an integrity boundary for normal local development, not a sandbox. It
does not claim protection from an actively racing malicious process running as
the repository owner, a compromised root account or kernel, or hostile storage
and dynamic-loader state. Such an actor can change bytes after inspection or
interfere with the process itself; defending against that requires a stronger
execution isolation model outside this Change.

`make check-fast`, `make check` and `make verify` are blocking command lanes.
`make quality-advisory` runs the repaired source and test architecture scanners
explicitly; those two repository-wide scanners remain advisory in this Change.

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
