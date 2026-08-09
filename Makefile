# flare-bootstrap-managed: v1

export UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
export STATE_TEST_WORKERS ?= 4

STATE_REPO ?= $(CURDIR)
STATE_TREE ?= HEAD
ALLURE_RESULTS ?= $(CURDIR)/.tmp/allure-results
ALLURE_REPORT ?= $(CURDIR)/.tmp/allure-report
ALLURE_CONFIG ?= $(CURDIR)/tools/quality/tests/project_state/allurerc.mjs
ALLURE ?= allure
ALLURE_PORT ?= 5050

.PHONY: doctor state-check state-static state-test state-allure state-allure-open check-fast check

doctor:
	@python3 tools/quality/check_repo_policy.py --doctor

state-check:
	@uv run --frozen --no-sync python -m tools.project_state.cli check --repo $(STATE_REPO) --tree $(STATE_TREE)

state-static:
	@uv run --frozen --no-sync ruff format --check tools/project_state tools/quality/source_manifest.py tools/quality/tests/project_state typings
	@uv run --frozen --no-sync ruff check tools/project_state tools/quality/source_manifest.py tools/quality/tests/project_state typings
	@uv run --frozen --no-sync mypy tools/project_state tools/quality/source_manifest.py tools/quality/tests/project_state

state-test:
	@uv run --frozen --no-sync python -m pytest -q -p no:cacheprovider -n $(STATE_TEST_WORKERS) --dist worksteal tools/quality/tests/project_state

state-allure:
	@FLARE_ALLURE_RESULTS=$(ALLURE_RESULTS) uv run --frozen --no-sync python -m pytest -q -p no:cacheprovider -n $(STATE_TEST_WORKERS) --dist worksteal --alluredir $(ALLURE_RESULTS) --clean-alluredir --allure-no-capture tools/quality/tests/project_state
	@uv run --frozen --no-sync python -m tools.quality.tests.project_state.runtime_evidence $(ALLURE_RESULTS) --repo $(CURDIR) --configured-workers $(STATE_TEST_WORKERS) --configured-distribution worksteal
	@uv run --frozen --no-sync python -m tools.quality.tests.project_state.allure_audit $(ALLURE_RESULTS)

state-allure-open: state-allure
	@$(ALLURE) generate $(ALLURE_RESULTS) --config $(ALLURE_CONFIG) --output $(ALLURE_REPORT) --open --port $(ALLURE_PORT)

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
