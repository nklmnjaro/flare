# Canonical dependency bundles v2

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
