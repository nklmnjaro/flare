import pytest

from tools.quality.tests.local_execution.command_scenarios import (
    verify_advisory_isolation,
    verify_architecture_green_and_intentional_red,
    verify_check_evidence_render_separation,
    verify_diagnose_semantics,
    verify_diagnostic_bounding,
    verify_dispatcher_negative_contract,
)
from tools.quality.tests.local_execution.support import LocalExecutionFixture


def test_architecture_red(
    local_execution_repository: LocalExecutionFixture,
) -> None:
    verify_architecture_green_and_intentional_red(local_execution_repository)


def test_dispatcher_negative(capsys: pytest.CaptureFixture[str]) -> None:
    verify_dispatcher_negative_contract(capsys)


def test_diagnose(
    local_execution_repository: LocalExecutionFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verify_diagnose_semantics(local_execution_repository, monkeypatch, capsys)


def test_status_separation(
    local_execution_repository: LocalExecutionFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verify_check_evidence_render_separation(local_execution_repository, capsys)


def test_bounding_and_global_safety(
    local_execution_repository: LocalExecutionFixture,
) -> None:
    verify_diagnostic_bounding(local_execution_repository)


def test_advisory_isolation(
    local_execution_repository: LocalExecutionFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_advisory_isolation(local_execution_repository, monkeypatch)
