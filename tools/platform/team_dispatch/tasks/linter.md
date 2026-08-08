# Linter / Quality Reviewer

Role: `kolyan_linter_reviewer`
Timing: `ACT_NOW`
Source: `${source_commit}`
Baseline SHA-256: `${baseline_sha256}`

## Goal
Independently review executable quality/static tooling. Admit a gate only with
unique signal, owner, intentional RED, legitimate exception and acceptable
false-positive/cost evidence. No linter zoo.

## TASK PREFLIGHT
Verify packet checksums, baseline, governance and actual source before review.
Do not promote gates merely because current checks are green.
