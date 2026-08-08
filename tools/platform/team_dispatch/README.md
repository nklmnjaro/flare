# Flare team dispatch

Repository-owned reproducible packaging for Flare engineering waves.

## Public command surface

```bash
make dispatch-doctor
make deps-build
make dispatch-build
make dispatch-verify
make foundation-package
```

`foundation-package` is the normal command. It requires a clean Git checkout,
builds the six accepted role dependency profiles, creates an exact
`git archive HEAD` baseline, creates one packet per team role, verifies the
result, and publishes stable local pointers under:

```text
.flare/artifacts/
├── baselines/
├── dependencies/
│   └── current -> dependency-dist-...
└── team-dispatch/
    └── current -> wave-...
```

`.flare/` is local managed state and must never be committed.

## Invariants

- exactly 9 team roles;
- exactly 6 dependency profiles;
- no umbrella `all` dependency bundle;
- source checkout must be clean;
- baseline is always `git archive HEAD`;
- generated artifacts are outside Git under `.flare/`;
- generated packets contain their exact source/bundle manifest;
- each engineering role gets only its own dependency profile;
- Product Owner and Gatekeeper packets are generated as `HOLD`;
- production freeze remains active until explicit `APPROVE FLARE-000`.

Tasks are templates. Source commit and baseline SHA are rendered at package
time, so task files do not need to be rewritten for every commit.
