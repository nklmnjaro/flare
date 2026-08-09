<!-- flare-bootstrap-managed: v1 -->
# Flare

**Test Execution Observability & Investigation Platform**

MVP promise:

> Flare shows a live pytest session and preserves verifiable evidence so a
> failure can be understood without manually switching between CI, reports,
> and fragmented logs.

Repository layout:

```text
backend/        Go canonical core
frontend/       SolidJS / TypeScript UI
sdk/python/     pytest SDK/plugin
contracts/      versioned contracts
deploy/         platform adapters
docs/           product / architecture / onboarding
tools/          project-owned quality tooling
```

Start with:

```bash
make doctor
make check-fast
```

See `docs/onboarding/START-HERE.md`.
