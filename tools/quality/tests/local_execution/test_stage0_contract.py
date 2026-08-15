import allure

from tools.quality.tests.local_execution.stage0_scenarios import (
    verify_stage0_environment_allowlist,
    verify_stage0_managed_python_reconstruction,
    verify_stage0_managed_tree_hardlink,
    verify_stage0_managed_tree_reconstruction,
    verify_stage0_poisoned_python,
    verify_stage0_poisoned_uv,
    verify_stage0_root_confinement,
    verify_stage0_shell_isolation,
    verify_stage0_unsupported_host,
    verify_stage0_uv_managed_python_isolation,
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

    @allure.title("[LF-STAGE0-003] Reconstruct unsealed managed Python")
    def test_managed_python_reconstruction(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_stage0_managed_python_reconstruction(local_execution_repository)

    @allure.title("[LF-STAGE0-004] Reconstruct an unsealed managed tree")
    def test_managed_tree_reconstruction(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_stage0_managed_tree_reconstruction(local_execution_repository)

    @allure.title("[LF-STAGE0-005] Ignore shell startup and caller locale")
    def test_shell_isolation(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_stage0_shell_isolation(local_execution_repository)

    @allure.title("[LF-STAGE0-006] Reject managed-tree hardlinks")
    def test_managed_tree_hardlink(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_stage0_managed_tree_hardlink(local_execution_repository)

    @allure.title("[LF-STAGE0-007] Reject an external intermediate Stage-0 root")
    def test_stage0_root_confinement(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_stage0_root_confinement(local_execution_repository)

    @allure.title("[LF-STAGE0-008] Never let uv inspect managed Python")
    def test_uv_managed_python_isolation(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_stage0_uv_managed_python_isolation(local_execution_repository)
