<!-- flare-bootstrap-managed: v1 -->
# Flare

**Test Execution Observability & Investigation Platform**

MVP promise:

> Flare shows a live pytest session and preserves verifiable evidence so a
> failure can be understood without manually switching between CI, reports,
> and fragmented logs.

Flare is an independently deployable, provider-neutral evidence add-on. It
connects to CI/CD and release systems without replacing their orchestration or
owning their lifecycle. Provider adapters stay outside the canonical core.

See
[`FLARE-PROVIDER-NEUTRAL-EVIDENCE-INTEGRATION-001`](docs/decisions/FLARE-PROVIDER-NEUTRAL-EVIDENCE-INTEGRATION-001.md)
for the product integration boundary.

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
