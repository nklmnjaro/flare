from pathlib import Path

import allure
import pytest

from tools.quality.tests.local_execution.admission_scenarios import (
    verify_activation_faults,
    verify_admission_performance,
    verify_admission_publication_bound,
    verify_bootstrap_rejects_old_environment,
    verify_bundle_python_contract,
    verify_candidate_observation_is_filesystem_only,
    verify_changed_package,
    verify_corrupt_admission,
    verify_extra_payload,
    verify_global_python_poisoning,
    verify_hook_admission,
    verify_launch_reconstruction_lock,
    verify_missing_admission,
    verify_planted_capabilities,
    verify_planted_doctor,
    verify_precise_concurrent_bootstrap,
    verify_python_symlink_escape,
    verify_read_only_admission,
    verify_replaced_project_python,
    verify_stale_repository,
    verify_uv_config_isolation,
    verify_valid_admitted_environment,
)
from tools.quality.tests.local_execution.stage0_inventory_scenarios import (
    verify_direct_execution_inventory,
)
from tools.quality.tests.local_execution.support import LocalExecutionFixture


@allure.parent_suite("Flare engineering contracts")
@allure.suite("Local-First execution")
@allure.feature("Stage-0 environment admission")
class TestAdmissionContract:
    def test_a001(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_planted_doctor(local_execution_repository)

    def test_a002(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_planted_capabilities(local_execution_repository)

    def test_a003(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_bootstrap_rejects_old_environment(local_execution_repository)

    def test_a004(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_missing_admission(local_execution_repository)

    def test_a005(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_corrupt_admission(local_execution_repository)

    def test_a006(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_stale_repository(local_execution_repository)

    def test_a007(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_replaced_project_python(local_execution_repository)

    def test_a008(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_python_symlink_escape(local_execution_repository)

    def test_a009(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_changed_package(local_execution_repository)

    def test_a010(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_extra_payload(local_execution_repository)

    def test_a011(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_valid_admitted_environment(local_execution_repository)

    def test_a012(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_precise_concurrent_bootstrap(local_execution_repository)

    def test_a013(self, tmp_path: Path) -> None:
        verify_activation_faults(tmp_path)

    def test_a014(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_hook_admission(local_execution_repository)

    def test_a015(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_bundle_python_contract(local_execution_repository)

    def test_a016(self, tmp_path: Path) -> None:
        verify_direct_execution_inventory(tmp_path)

    def test_a017(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_global_python_poisoning(local_execution_repository)

    def test_a018(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_read_only_admission(local_execution_repository)

    def test_a019(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_admission_performance(local_execution_repository)

    def test_a020(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_uv_config_isolation(local_execution_repository)

    def test_a021(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_launch_reconstruction_lock(local_execution_repository)

    def test_a022(self, local_execution_repository: LocalExecutionFixture) -> None:
        verify_candidate_observation_is_filesystem_only(local_execution_repository)

    def test_a023(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        verify_admission_publication_bound(tmp_path, monkeypatch)
