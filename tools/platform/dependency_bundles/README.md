# Canonical dependency bundles v3

Profiles:

```text
backend
frontend
qa1
qa2
platform
linter
```

There is intentionally no reviewer bundle.

Split:

```text
backend   -> Go + contracts
frontend  -> Node/pnpm
qa1       -> Python QA + contracts
qa2       -> Python QA2
platform  -> kubectl + helm + minikube
linter    -> Python quality + Hadolint/actionlint/kubeconform
reviewer  -> no dependency bundle
```

The reviewer receives exact source/governance/evidence only. If an executable
rerun is needed, temporarily provide the exact accepted role bundle being
reviewed.

Default hard publication budget:

```text
300 MiB per dependency bundle
```


Restore contract:

```text
bundle integrity + link safety
→ target preflight
→ materialize versioned candidate
→ validate supported tool surface and declared versions
→ validate profile postconditions
→ atomic current switch
```

The restore never mutates the project `.venv`. Python profile environments live
inside the versioned profile state.

`profile-toolchain.tsv` is the supported direct tool surface. Every entry must
have a real source manifest record (except `gofmt`, which is derived from the
declared Go runtime) and a version that the restored candidate can prove.

Activation is fail-fast for missing supported tools and required commands. It
must not modify caller shell options or traps.

An accepted bundle must pass both positive restore checks and intentional RED
cases for:

- candidate validation failure;
- wrong declared tool version;
- missing supported tool;
- invalid or stale current state;
- unsafe payload symlink;
- corrupted checksum before target mutation.

The synthetic suite also preserves a minimal pre-fix ordering fixture so the
original atomicity defect remains reproducible as intentional RED evidence.

`restore_role_bundle.sh` runs the canonical archive verifier before extraction;
consumer restore must not bypass archive safety validation.
