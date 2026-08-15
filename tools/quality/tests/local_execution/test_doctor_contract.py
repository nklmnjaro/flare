import allure
import pytest

from tools.quality.tests.local_execution.doctor_scenarios import (
    verify_doctor_read_only,
    verify_healthy_doctor,
    verify_missing_required_doctor,
    verify_poisoned_python_path,
    verify_unsupported_host,
    verify_wrong_versions_doctor,
)
from tools.quality.tests.local_execution.support import LocalExecutionFixture


@allure.parent_suite("Flare engineering contracts")
@allure.suite("Local-First execution")
@allure.feature("Doctor")
class TestDoctorContract:
    @allure.title("[LF-N08] Accept a healthy supported host")
    def test_healthy(
        self,
        local_execution_repository: LocalExecutionFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        verify_healthy_doctor(local_execution_repository, monkeypatch)

    @allure.title("[LF-N09] Reject a missing required prerequisite")
    def test_missing_required(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_missing_required_doctor(local_execution_repository)

    @allure.title("[LF-N10] Reject wrong Python and uv versions")
    def test_wrong_versions(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_wrong_versions_doctor(local_execution_repository)

    @allure.title("[LF-N11] Reject an unsupported host profile")
    def test_unsupported_host(
        self, local_execution_repository: LocalExecutionFixture
    ) -> None:
        verify_unsupported_host(local_execution_repository)

    @allure.title("[LF-N12] Keep healthy and failing doctor read-only")
    def test_read_only(
        self,
        local_execution_repository: LocalExecutionFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        verify_doctor_read_only(local_execution_repository, monkeypatch)

    @allure.title("[LF-N13] Ignore poisoned PATH Python")
    def test_poisoned_python(
        self,
        local_execution_repository: LocalExecutionFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        verify_poisoned_python_path(local_execution_repository, monkeypatch)
