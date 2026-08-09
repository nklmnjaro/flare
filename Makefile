# flare-bootstrap-managed: v1

.PHONY: doctor bootstrap check-fast check verify diagnose state-check state-static state-test state-allure state-allure-open

doctor:
	@./flare doctor

bootstrap:
	@./flare bootstrap

state-check:
	@./flare state-check

state-static:
	@./flare state-static

state-test:
	@./flare state-test

state-allure:
	@./flare state-allure

state-allure-open:
	@./flare state-allure-open

check-fast:
	@./flare check-fast

check:
	@./flare check

verify:
	@./flare verify

diagnose:
	@./flare diagnose

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
