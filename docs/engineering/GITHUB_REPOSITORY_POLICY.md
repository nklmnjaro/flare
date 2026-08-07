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

## Important

AI/Gatekeeper review in ChatGPT is an engineering governance step, but it is not a
GitHub approval. Do not configure an impossible GitHub approval count.

## CI source of truth

GitHub Actions calls project commands (`make check-fast`, later `make check`).
Do not move business/quality logic into workflow YAML.

## Security

Default workflow token should be read-only. Escalate permissions per job only when a
specific operation requires it.
