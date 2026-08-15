import os
from dataclasses import replace
from pathlib import Path

import pytest

from tools.local_execution.bootstrap import bootstrap_environment
from tools.local_execution.doctor import PlatformFacts, inspect_doctor
from tools.local_execution.model import CheckStatus
from tools.quality.tests.local_execution.assertions import (
    assert_contains,
    assert_equal,
    assert_false,
    assert_not_contains,
    assert_true,
)
from tools.quality.tests.local_execution.reporting import scenario
from tools.quality.tests.local_execution.support import (
    LocalExecutionFixture,
    complete_snapshot,
    write_fake_uv,
)


def _supported(repository: LocalExecutionFixture) -> PlatformFacts:
    profile = repository.profile
    return PlatformFacts(
        profile.os,
        profile.os_release_id,
        profile.os_release_version,
        profile.architecture,
    )


def _bootstrapped_python(repository: LocalExecutionFixture) -> Path:
    result = bootstrap_environment(
        repository.root,
        repository.profile,
        repository.uv,
        repository.managed_python,
    )
    assert_true(result.passed, "doctor fixture bootstrap")
    return repository.root / repository.profile.project_environment / "bin/python"


@scenario("LF-N08", "Accept a healthy supported host")
def verify_healthy_doctor(
    repository: LocalExecutionFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python = _bootstrapped_python(repository)
    monkeypatch.setenv(
        "UV_INDEX_URL", "https://fixture-user:fixture-secret@example.invalid/simple"
    )
    report = inspect_doctor(
        repository.root,
        repository.profile,
        repository.uv,
        python,
        facts=_supported(repository),
        optional_path="",
    )
    optional = tuple(
        item for item in report.observations if item.name == "allure_renderer"
    )
    assert_true(report.passed, "healthy doctor")
    assert_equal(len(optional), 1, "optional observation count")
    assert_equal(
        optional[0].status,
        CheckStatus.OPTIONAL_MISSING,
        "optional renderer classification",
    )
    assert_contains("UV_INDEX_URL", report.render(), "source configuration name")
    assert_not_contains("fixture-secret", report.render(), "doctor source diagnostic")


@scenario("LF-N09", "Reject a missing required prerequisite")
def verify_missing_required_doctor(repository: LocalExecutionFixture) -> None:
    python = _bootstrapped_python(repository)
    profile = replace(
        repository.profile,
        required_host_commands=(
            *repository.profile.required_host_commands,
            "/definitely/missing/flare-tool",
        ),
    )
    report = inspect_doctor(
        repository.root,
        profile,
        repository.uv,
        python,
        facts=_supported(repository),
    )
    assert_false(report.passed, "missing required command")
    assert_contains("declared host trust root missing", report.render(), "doctor")


@scenario("LF-N10", "Reject wrong Python and uv versions")
def verify_wrong_versions_doctor(repository: LocalExecutionFixture) -> None:
    python = _bootstrapped_python(repository)
    wrong_profile = replace(repository.profile, python_implementation="pypy")
    wrong_uv = write_fake_uv(repository.root, name="uv-wrong", version="0.1.0")
    report = inspect_doctor(
        repository.root,
        wrong_profile,
        wrong_uv,
        python,
        facts=_supported(repository),
    )
    rendered = report.render()
    assert_false(report.passed, "wrong runtime versions")
    assert_contains("Python implementation mismatch", rendered, "doctor")
    assert_contains("uv version mismatch", rendered, "doctor")


@scenario("LF-N11", "Reject an unsupported host profile")
def verify_unsupported_host(repository: LocalExecutionFixture) -> None:
    python = _bootstrapped_python(repository)
    report = inspect_doctor(
        repository.root,
        repository.profile,
        repository.uv,
        python,
        facts=PlatformFacts("Darwin", "macos", "15", "arm64"),
    )
    assert_false(report.passed, "unsupported host")
    assert_contains("detected=Darwin/macos-15/arm64", report.render(), "doctor")
    assert_contains(repository.profile.profile_id, report.render(), "doctor profile")


@scenario("LF-N12", "Keep healthy and failing doctor read-only")
def verify_doctor_read_only(
    repository: LocalExecutionFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python = _bootstrapped_python(repository)
    wrong_uv = write_fake_uv(repository.root, name="uv-wrong", version="0.0.0")
    wrong_runtime_profile = replace(repository.profile, python_implementation="pypy")
    missing_profile = replace(
        repository.profile,
        required_host_commands=(
            *repository.profile.required_host_commands,
            "/definitely/missing/flare-read-only",
        ),
    )
    poison = repository.root / "read-only-poison"
    poison.mkdir()
    for name in ("python", "python3", "uv"):
        target = poison / name
        target.write_text("#!/bin/sh\nexit 89\n", encoding="utf-8")
        target.chmod(0o755)
    before = complete_snapshot(repository.root)
    healthy = inspect_doctor(
        repository.root,
        repository.profile,
        repository.uv,
        python,
        facts=_supported(repository),
    )
    wrong = inspect_doctor(
        repository.root,
        repository.profile,
        wrong_uv,
        python,
        facts=_supported(repository),
    )
    missing = inspect_doctor(
        repository.root,
        missing_profile,
        repository.uv,
        python,
        facts=_supported(repository),
    )
    wrong_runtime = inspect_doctor(
        repository.root,
        wrong_runtime_profile,
        repository.uv,
        python,
        facts=_supported(repository),
    )
    monkeypatch.setenv("PATH", f"{poison}:/usr/bin:/bin")
    poisoned = inspect_doctor(
        repository.root,
        repository.profile,
        repository.uv,
        python,
        facts=_supported(repository),
    )
    after = complete_snapshot(repository.root)
    assert_true(healthy.passed, "healthy doctor")
    assert_false(wrong.passed, "failing doctor")
    assert_false(missing.passed, "missing prerequisite doctor")
    assert_false(wrong_runtime.passed, "wrong Python doctor")
    assert_true(poisoned.passed, "explicit identities under PATH poisoning")
    assert_equal(after, before, "doctor filesystem snapshot")


@scenario("LF-N13", "Ignore poisoned PATH executable names")
def verify_poisoned_python_path(
    repository: LocalExecutionFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python = _bootstrapped_python(repository)
    poison = repository.root / "poison"
    poison.mkdir()
    for name in ("python", "python3", "python3.14", "uv"):
        target = poison / name
        target.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
        target.chmod(0o755)
    monkeypatch.setenv("PATH", f"{poison}:{os.environ.get('PATH', '')}")
    report = inspect_doctor(
        repository.root,
        repository.profile,
        repository.uv,
        python,
        facts=_supported(repository),
    )
    assert_true(report.passed, "explicit project Python under PATH poisoning")
