# GitHub repository policy

GitHub is an adapter around project-owned commands and rules.

## Main

Target policy:

- pull request before merge;
- squash only;
- linear history;
- force pushes blocked;
- deletion blocked;
- review conversations resolved;
- `repo-policy` required;
- human approval count depends on available real GitHub reviewers.

### A.1 exact coordination publication exception

The squash-only rule remains mandatory for source and ordinary governance
changes. One narrow exception permits the exact commit produced by the accepted
A.1 coordination-state publisher to fast-forward `main` after review.

Every condition below is required:

- the publisher builds the candidate from the exact current `main` commit and
  expected source-state SHA-256;
- if `accepted_source_baseline.git_commit` changes, its new commit is already
  reachable from that exact `main` parent and was therefore integrated under
  the ordinary source pull-request and squash policy;
- the candidate has exactly one parent, equal to that `main` commit;
- its diff contains only `docs/project/state.json` and the generated
  `docs/project/CURRENT_STATE.md` projection;
- the exact candidate passes A.1 validation and `make state-check`;
- a pull request from the exact candidate is open, its required checks pass,
  and its review conversations are resolved;
- immediately before publication, remote `main`, the candidate parent, and the
  expected state preimage still match;
- publication is an ordinary fast-forward push of the full candidate object ID,
  never a force push, and fails closed if `main` moved.

GitHub may record that pull request as indirectly merged after the exact
fast-forward. This exception does not authorize rebasing, merging, squashing,
mutating the validated candidate, or bypassing pull requests for any other
change.

## Important

AI/Gatekeeper review in ChatGPT is an engineering governance step, but it is not a
GitHub approval. Do not configure an impossible GitHub approval count.

## CI source of truth

GitHub Actions calls project commands (`make check-fast`, later `make check`).
Do not move business/quality logic into workflow YAML.

## Security

Default workflow token should be read-only. Escalate permissions per job only when a
specific operation requires it.
