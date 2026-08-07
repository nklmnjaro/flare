# flare-bootstrap-managed: v1

.PHONY: doctor check-fast check

doctor:
	@python3 tools/quality/check_repo_policy.py --doctor

check-fast:
	@python3 tools/quality/check_repo_policy.py

check: check-fast
	@echo "Full language/platform gates are added only by reviewed Flare tasks."
