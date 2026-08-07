# Flare canonical dependency-bundle source

Authoritative repository location:

```text
tools/platform/dependency_bundles/
```

This source builds the six active engineering-role bundles:

```text
backend
frontend
qa1
qa2
platform
linter
```

It intentionally does **not** build `all`.

Restore contract:

```text
bundle integrity/safety preflight
→ target-state preflight
→ versioned candidate materialize
→ candidate validation
→ single atomic `current` switch
```

A failed candidate must not change the previous `current` environment.

Python environments are stored inside the versioned profile state. Restore does
not create, delete or replace repository `.venv`; activation uses the selected
profile's own versioned `venv` directly.

QA2 Foundation bundles intentionally do not include Chromium binaries while
browser Product E2E remains NOT_APPLICABLE in the current Foundation wave.

Distribution criterion:

```text
BUNDLE ACCEPTANCE PASS: <profile>
```

Archive-only `BUNDLE PASS` is not enough.
