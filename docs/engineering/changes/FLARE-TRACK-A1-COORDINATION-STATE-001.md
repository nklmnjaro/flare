---
change_id: "FLARE-TRACK-A1-COORDINATION-STATE-001"
status: "ACCEPTED / READY FOR BOUNDED CODE"
implementation_authorization: "AUTHORIZED"
---

# Flare Track A.1 — Coordination State Contract v1.0

**Semantic class:** `BOUNDARY`
**Risk flags:** `data_integrity`, `operability`, `reliability`

## Acceptance provenance

Accepted on `2026-08-08`.

```text
Product Owner:
ACCEPT_A1_READY_FOR_CODE

Gatekeeper:
ACCEPT_A1_READY_FOR_CODE
```

Reviewed final acceptance pack SHA-256:

```text
7278f17754387cc2fa9a594093dbda413e59273be74ef55ff41c0091fcd30423
```

Authorization is limited to the smallest implementation required to prove
`FLARE-TRACK-A1-COORDINATION-STATE-001`.

Still not authorized:

```text
A.2 HANDOFF v1
A.3 broader aggregation/orchestration
Frontend Track B
product runtime
production
APPROVE FLARE-000
```

## Goal

Create the smallest fail-closed repository coordination-state contract that lets
Flare workers and a replacement Analyst recover current engineering work without
chat archaeology and without creating a second product constitution.

## Ownership

```text
Decision owner:
Product Owner / Main Coordinator

Disposition / consistency:
Analyst

Bounded implementation owner:
Platform

Independent contract proof:
QA1 + Linter/Quality

Replacement usability proof:
QA2

Consumers:
all current Flare roles
```

## Canonical files

```text
docs/project/state.json
docs/project/CURRENT_STATE.md
```

`state.json` is the one canonical machine coordination index.

`CURRENT_STATE.md` is a bounded human-readable summary generated or mechanically
verified from the same validated candidate. It guarantees exact display of the
project/schema identity, accepted source baseline, product/gate references,
Integrator principal, active Change identities/contracts, next actions and open
blockers. It is not a recovery database and is never independently authored as
a second truth. Complete recovery always starts from `state.json` and its
referenced authorities.

## Machine format

JSON is accepted.

Canonical state bytes:

```text
UTF-8
LF line endings
2-space indentation
lexicographically sorted object keys
ensure_ascii=false
exactly one trailing LF
no floats in schema
```

Set-like arrays are sorted by stable identifier for serialization.

Raw JSON parsing rejects duplicate object keys.

No YAML/TOML multi-format mode.

## Coordination state scope

State stores only current coordination facts and resolvable references:

```text
schema_version
project_id

accepted_source_baseline:
  git_commit
  optional source_artifact_id

product_phase_ref
production_gate_ref

integrator:
  assignee_ref
  assignment_ref

role_registry_ref
enforcement_matrix_ref

active_changes:
  change_id
  contract_ref
  required_artifact_ids

open_decisions:
  product refs
  technical refs

open_blockers:
  blocker_id
  blocker_ref
  blocks_change_ids

accepted_artifacts:
  artifact_id
  kind
  sha256
  manifest_ref

next_action_change_ids
```

## Explicitly excluded

State does not independently author:

```text
actual current Git HEAD
branch name as identity
timestamps as identity
product/protocol/security/architecture prose
implementation acceptance criteria
copied gate maturity
copied production authorization
copied Change owner/class/status
blocker prose
artifact download/provider mechanics
historical completed waves
free-form roadmap/history
numeric state_revision
```

Normative semantics remain in their versioned authoritative sources.

## Accepted source baseline

`accepted_source_baseline.git_commit` is the immutable source/integration
baseline consumed by active work.

It is distinct from the coordination commit/tree that contains current
`state.json`.

Actual coordination Git HEAD/ref identity is runtime-derived and is not stored
as self-referential "current HEAD" inside state.

If exact source archive/content bytes are required:

```text
accepted_source_baseline.source_artifact_id
```

must resolve to `accepted_artifacts`, whose manifest binds to the same
`git_commit`.

Mismatch:

```text
CONTRADICTION
```

No filename/timestamp identity.

## Coordination repository references

Repo-relative refs resolve against the exact candidate coordination tree during
candidate validation and against the containing coordination Git tree during
read/replacement.

They do not silently resolve against:

```text
accepted source baseline
arbitrary dirty working-tree content
host absolute paths
```

Authoritative repo refs reject:

```text
absolute paths
..
root escape
untracked target
symlink authoritative target
missing target
wrong required document ID
wrong required document status
```

## Product phase / production / enforcement

State uses references only:

```text
product_phase_ref
production_gate_ref
enforcement_matrix_ref
```

It does not copy their normative status prose/maps.

For current Flare, production authorization remains the separate FLARE-000
source.

Implementation authorization is **per active Change**, derived from its exact
Change/Iteration Contract.

Implementation authorization never implies production authorization.

## Integrator

`Integrator` is a process responsibility, not a tenth role.

State contains:

```text
integrator.assignee_ref
integrator.assignment_ref
```

`assignee_ref` must resolve through the authoritative role registry to exactly
one current principal/member.

`assignment_ref` must resolve to the authoritative basis for that assignment or
delegation.

The accepted default assignment belongs to `Product Owner / Main Coordinator`.
The role registry must identify its current structured principal, and the
referenced assignment record must bind that exact role. A later explicit
authoritative delegation may replace this default.

Zero/multiple principals or invalid/superseded assignment:

```text
STATE_DEFECT
```

No implicit fallback or automatic reassignment.

## Active Changes

Each active Change record contains only:

```text
change_id
contract_ref
required_artifact_ids
```

The referenced Change/Iteration Contract remains authoritative for:

```text
owner
semantic class
lifecycle status
implementation authorization
acceptance semantics
```

Validator confirms that the listed Change is in an allowed coordination-active
state.

## Decisions

Open Product and Technical decisions are references.

State does not duplicate the decision prose.

Unresolvable/stale required decision ref:

```text
STATE_DEFECT
```

## Blockers

Each blocker contains:

```text
blocker_id
blocker_ref
blocks_change_ids
```

Every blocked Change must exist in `active_changes`.

Blocker owner/severity/details live in the referenced authoritative blocker or
evidence source.

## Accepted artifacts

Each artifact contains:

```text
artifact_id
kind
sha256
manifest_ref
```

Artifact manifest remains authoritative for:

```text
resolution
provenance
compatibility
platform/tool metadata
```

Required artifact applicability is Change-scoped through
`active_changes[].required_artifact_ids`.

Role-wide artifact applicability is not duplicated in state.

## Next actions

`next_action_change_ids` is:

```text
unique
unordered
subset of active_changes
contract-resolvable
currently actionable by the referenced Change contract
unblocked
```

Array order carries no priority or scheduling semantics.

If there is no safe next action, at least one resolvable open blocker or open
decision must explain why continuation is not safe.

No separate numeric limit is needed beyond the finite active-Change set.

## Validation pipeline

Normative stage order:

```text
1. raw bytes
2. strict JSON parse with duplicate-key rejection
3. accepted JSON Schema structural validation only
4. strict typed external-state parsing
5. semantic / invariant / reference validation
6. projection generation + projection validation
7. publication-specific concurrency checks
```

An earlier failed stage is not reinterpreted by later stages.

JSON Schema validates structure/types/basic format only.
Repository, artifact, ownership, lifecycle and cross-reference semantics belong
to semantic/reference validation.

The accepted schema is a closed immutable structural contract. Candidate bytes
must match its accepted content identity; `$id` alone is not authentication.
Candidate-controlled external schema resolution is forbidden.

## Validation result

Top-level:

```text
PASS
STATE_DEFECT
```

`STATE_DEFECT` contains stable findings.

Finding semantics:

```text
identity = stable finding code + stable field/reference context
order = non-semantic
logical duplicates = deduplicated
```

Machine serialization may sort findings deterministically.

If an implementation caps collected findings:

```text
truncation must be explicit and machine-readable
STATE_DEFECT remains STATE_DEFECT
absence of an omitted finding must not be inferred
```

Each negative fixture asserts at least one required stable finding code/context.

Representative stable codes:

```text
UNSUPPORTED_SCHEMA
DUPLICATE_KEY
MISSING_REFERENCE
UNRESOLVABLE_REFERENCE
INVALID_PATH
SHA_MISMATCH
CONTRADICTION
INVALID_INTEGRATOR
INVALID_CHANGE
INVALID_ARTIFACT
INVALID_NEXT_ACTION
PROJECTION_MISMATCH
```

`STALE_PREIMAGE` is a publication outcome, not a state-validation finding.

## Publication precondition / lost-update semantics

A publication attempt is built from an exact runtime-derived coordination
parent/ref identity.

Publication evidence carries externally:

```text
expected_coordination_parent_commit
expected_source_state_sha256
candidate_coordination_commit
candidate_state_sha256
```

Contract:

1. candidate is built from the exact expected coordination parent;
2. all repo refs resolve against that exact candidate/parent model;
3. strict parse/schema/semantic/reference validation passes;
4. `CURRENT_STATE.md` is generated from that exact validated candidate;
5. immediately before publication, canonical state bytes and canonical
   coordination ref are compared with the expected preimage;
6. publication atomically updates the canonical coordination ref from the exact
   expected parent to the exact validated candidate commit/tree.

If either expected state SHA or expected parent/ref no longer matches:

```text
STALE_PREIMAGE
```

and accepted coordination state is not mutated.

After final validation:

```text
automatic rebase
automatic merge
candidate mutation
```

is forbidden.

A new bounded publication attempt must rebuild/revalidate from the new parent.

Concurrency invariant:

> Two publishers starting from the same accepted coordination parent cannot both
> publish. Exactly one may win the atomic compare-and-swap; every loser fails
> closed without accepted-state mutation.

The concrete Git primitive/lock implementation remains bounded A.1
implementation work.

No database/distributed lock/state service is required.

## State + projection publication

`state.json` and generated `CURRENT_STATE.md` belong to one validated candidate
coordination commit/tree.

They must not be published as independently accepted steps.

A byte-synchronized but semantically invalid candidate is still invalid.

## Review-target process ratchet

Future structured review target identity must bind:

```text
review semantic payload
+
canonical reviewer assignment/scope
```

A.1 verifies one structured ReviewResponse at a time:

```text
reviewer role
exact target identity
exact canonical assigned topics/scope
```

A stale response from an earlier assignment cannot be reused after reviewer
scope changes.

A.3 owns collections of responses, duplicate-response identity, supersession
ordering and authoritative aggregation. A.1 does not define or implement those
semantics.

This is process-review identity hardening; it is not a `state.json` field.

## A.1 command-evidence security boundary

Raw command argv is execution-only test-support data. It is never stored in the
durable `CommandResult` or attached to Allure. Durable command presentation is
constructed from a separately sanitized argv representation, shell-rendered,
then sanitized again before persistence. Failure diagnostics use only that safe
presentation and explicit structured failure fields; they never serialize raw
subprocess exceptions or their argv.

Captured stdout and stderr are decoded, redacted and only then bounded. An
explicit redaction marker and an explicit truncation marker describe different
operations.

The supported secret names are exactly, case-insensitively:

```text
authorization
password
secret
token
```

The bounded recognized grammar is:

```text
key=value
key: value
optionally single- or double-quoted exact key
--key=value
separate argv elements: --key VALUE
assignment after actual LF or CR
assignment after literal escaped \n or \r
```

Embedded source/script arguments containing a recognized assignment are
replaced as a whole rather than parsed as another language. This contract does
not claim discovery of unlabelled, differently named, encoded, encrypted or
obfuscated secrets and is not a generic DLP system.

The A.1 raw-evidence auditor independently searches for the configured exact
synthetic canary. It does not reuse the producer matcher or infer safety from a
redaction marker. Accepted textual attachment media types are exactly
`text/plain` and `application/json`; title does not affect scanning. Missing,
orphaned, invalid-UTF-8, unknown or binary attachment evidence fails closed for
this A.1 result set. A future binary-evidence policy requires a separate
reviewed contract.

## Mandatory negative scenarios

Future A.1 implementation proof must include at least:

1. unsupported schema;
2. duplicate JSON key;
3. absolute/root-escaping repo path;
4. authoritative ref is symlink/untracked/missing;
5. wrong document ID/status;
6. accepted source commit missing;
7. source artifact manifest binds to another commit;
8. artifact ID collision;
9. artifact SHA mismatch;
10. required artifact unresolvable;
11. zero/multiple Integrator resolution;
12. invalid/superseded Integrator assignment;
13. active Change contract missing;
14. active Change in non-active lifecycle state;
15. blocker references unknown Change;
16. next action unknown;
17. next action blocked;
18. next action non-actionable by Change contract;
19. no next action and no blocker/decision explanation;
20. Enforcement Matrix ref missing/invalid;
21. production gate ref missing/invalid;
22. product phase ref missing/invalid;
23. projection built from another candidate;
24. two simultaneous defects produce deterministic set semantics;
25. findings collection truncation is explicitly observable;
26. stale state SHA preimage;
27. coordination ref moved while state bytes stayed identical;
28. two publishers race from the same parent; only one publishes;
29. candidate is automatically rebased/merged after validation → rejected;
30. current working tree has a ref absent from candidate coordination tree;
31. review response targets wrong semantic payload;
32. review response targets correct semantic payload but stale reviewer
    assignment.

Round-2 defect-closure regressions use the separate `A1-Cxx` namespace. They
extend this proof surface without renumbering or redefining `A1-N01..A1-N32`.

## Non-goals

A.1 does not define:

```text
HANDOFF v1 schema
handoff payload/sidecar hashing
generic artifact registry/service
replacement drill implementation
frontend dependency environment
CI provider wiring
product runtime
FLARE-000 approval
new gate promotion
clean-checkout bootstrap or dependency provisioning
```

This closure is verified in the available prepared environment and makes no
clean-checkout reconstruction claim. `FLARE-LOCAL-PIPELINE` owns future
doctor/preflight, Python and uv convergence, `uv sync --frozen`, and external
tool provisioning.

## Ready-for-code gate

A.1 becomes `READY_FOR_CODE` only after Product Owner and Gatekeeper accept this
final Iteration Contract.

That authorization is limited to the smallest implementation required to prove
this A.1 contract.

A.2/A.3 remain separate changes.
