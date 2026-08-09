import allure

from tools.quality.tests.local_execution.stage0_scenarios import (
    verify_stage0_environment_allowlist,
    verify_stage0_poisoned_python,
    verify_stage0_poisoned_uv,
    verify_stage0_unsupported_host,
)
from tools.quality.tests.local_execution.support import LocalExecutionFixture


@allure.parent_suite("Flare engineering contracts")
@allure.suite("Local-First execution")
@allure.feature("Stage-0 trust boundary")
class TestStage0Contract:
    @allure.title("[LF-N19] Reject unsupported hosts before bootstrap mutation")
    def test_unsupported_host(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_stage0_unsupported_host(local_execution_repository)

    @allure.title("[LF-N20] Reject poisoned uv identity and behavior")
    def test_poisoned_uv(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_stage0_poisoned_uv(local_execution_repository)

    @allure.title("[LF-N21] Ignore PATH Python and use reconstructed environment")
    def test_poisoned_python(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_stage0_poisoned_python(local_execution_repository)

    @allure.title("[LF-N22] Keep bootstrap free of global mutation commands")
    def test_environment_allowlist(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_stage0_environment_allowlist(local_execution_repository)
