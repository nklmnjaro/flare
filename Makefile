# flare-bootstrap-managed: v1

.PHONY: doctor check-fast check

doctor:
	@python3 tools/quality/check_repo_policy.py --doctor

check-fast:
	@python3 tools/quality/check_repo_policy.py

check: check-fast
	@echo "Full language/platform gates are added only by reviewed Flare tasks."

# Repository-owned Flare engineering dispatch facade.
dispatch-doctor:
	python3 tools/platform/team_dispatch/build.py doctor --repo .

deps-build:
	python3 tools/platform/team_dispatch/build.py deps --repo .

dispatch-build:
	python3 tools/platform/team_dispatch/build.py dispatch --repo .

dispatch-verify:
	python3 tools/platform/team_dispatch/build.py verify --repo .

foundation-package:
	python3 tools/platform/team_dispatch/build.py all --repo .
