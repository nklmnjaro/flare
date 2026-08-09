import allure
import pytest

from tools.quality.tests.local_execution.command_scenarios import (
    verify_architecture_green_and_intentional_red,
    verify_check_evidence_render_separation,
    verify_diagnose_semantics,
    verify_diagnostic_bounding,
    verify_dispatcher_negative_contract,
)
from tools.quality.tests.local_execution.support import LocalExecutionFixture


@allure.parent_suite("Flare engineering contracts")
@allure.suite("Local-First execution")
@allure.feature("Command ownership")
class TestCommandContract:
    @allure.title("[LF-N14] Detect policy duplication in adapters")
    def test_architecture_red(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_architecture_green_and_intentional_red(local_execution_repository)

    @allure.title("[LF-N15] Reject unknown and duplicate capabilities")
    def test_dispatcher_negative(self, capsys: pytest.CaptureFixture[str]) -> None:
        verify_dispatcher_negative_contract(capsys)

    @allure.title("[LF-N16] Diagnose multiple findings without claiming green")
    def test_diagnose(
        self,
        local_execution_repository: LocalExecutionFixture,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        verify_diagnose_semantics(local_execution_repository, monkeypatch, capsys)

    @allure.title("[LF-N17] Separate check, evidence and render outcomes")
    def test_status_separation(
        self,
        local_execution_repository: LocalExecutionFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        verify_check_evidence_render_separation(local_execution_repository, capsys)

    @allure.title("[LF-N18] Bound diagnostics and forbid global mutation")
    def test_bounding_and_global_safety(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_diagnostic_bounding(local_execution_repository)
