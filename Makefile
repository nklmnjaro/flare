# flare-bootstrap-managed: v1

.PHONY: doctor bootstrap check-fast check verify diagnose quality-advisory \
	state-check state-static state-test state-allure state-allure-open

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

quality-advisory:
	@./flare quality-advisory
