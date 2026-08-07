# Flare

**Test Execution Observability & Investigation Platform**

Current product target:

> Flare shows a live pytest session and preserves verifiable evidence so a
> failure can be understood without manually switching between CI, reports,
> and fragmented logs.

## Repository

```text
backend/        Go canonical core
frontend/       SolidJS / TypeScript UI
sdk/python/     pytest SDK/plugin
contracts/      versioned contracts
deploy/         platform adapters
docs/           product, architecture, onboarding
tools/          quality and project tooling
```

Start with:

```bash
make doctor
make check-fast
```

See `docs/onboarding/START-HERE.md`.
