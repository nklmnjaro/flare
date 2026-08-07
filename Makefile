.PHONY: doctor check-fast check

doctor:
	@python3 tools/quality/check_repo_policy.py --doctor

check-fast:
	@python3 tools/quality/check_repo_policy.py

check: check-fast
	@echo "Full project gates are intentionally not defined until FLARE-000."
