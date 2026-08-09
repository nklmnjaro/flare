import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from tools.local_execution.__main__ import main
from tools.local_execution.architecture import audit_execution_ownership
from tools.local_execution.commands import (
    HANDLER_PAIRS,
    build_dispatch,
    dispatch,
)
from tools.local_execution.model import PUBLIC_CAPABILITIES, Capability, ProcessResult
from tools.local_execution.process import CommandContext, ProcessSpec, run_process
from tools.local_execution.profile import HostProfile
from tools.quality.tests.local_execution.assertions import (
    assert_contains,
    assert_equal,
    assert_not_contains,
    assert_raises,
    assert_true,
)
from tools.quality.tests.local_execution.reporting import (
    attach_text,
    scenario,
    step_context,
)
from tools.quality.tests.local_execution.support import LocalExecutionFixture


@scenario("LF-N14", "Detect policy duplication in adapters")
def verify_architecture_green_and_intentional_red(
    repository: LocalExecutionFixture,
) -> None:
    makefile = (repository.root / "Makefile").read_text(encoding="utf-8")
    stage0 = (repository.root / "flare").read_text(encoding="utf-8")
    good = audit_execution_ownership(makefile, stage0)
    make_red = audit_execution_ownership(
        makefile.replace("@./flare check-fast", "ruff check tools"), stage0
    )
    stage0_red = audit_execution_ownership(makefile, stage0 + "\npytest -q\n")
    assert_equal(good, (), "known-good architecture findings")
    assert_true(
        any(item.code == "MAKEFILE_POLICY_DUPLICATION" for item in make_red),
        "Makefile intentional RED",
    )
    assert_true(
        any(item.code == "STAGE0_POLICY_DUPLICATION" for item in stage0_red),
        "Stage-0 intentional RED",
    )


@scenario("LF-N15", "Reject unknown and duplicate capabilities")
def verify_dispatcher_negative_contract(capsys: pytest.CaptureFixture[str]) -> None:
    result = main(["not-a-capability"])
    captured = capsys.readouterr()

    def duplicate() -> None:
        build_dispatch((*HANDLER_PAIRS, HANDLER_PAIRS[0]))

    error = assert_raises(ValueError, duplicate, "duplicate dispatch")
    expected_stage1 = set(PUBLIC_CAPABILITIES) - {Capability.BOOTSTRAP}
    actual_stage1 = {
        capability
        for capability, _ in HANDLER_PAIRS
        if capability in PUBLIC_CAPABILITIES
    }
    assert_equal(result, 2, "unknown capability exit")
    assert_contains("unknown capability", captured.err, "unknown stderr")
    assert_contains("duplicate capability", str(error), "duplicate error")
    assert_not_contains("importlib", captured.err, "unknown dispatch")
    assert_equal(actual_stage1, expected_stage1, "public Stage-1 implementations")


@scenario("LF-N16", "Diagnose multiple findings without claiming green")
def verify_diagnose_semantics(
    repository: LocalExecutionFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    def failing_doctor(root: Path, profile: HostProfile, uv: Path) -> int:
        del root, profile, uv
        print("doctor=FAIL")
        return 1

    def runner(specification: ProcessSpec, root: Path) -> ProcessResult:
        del root
        calls.append(specification.label)
        code = 1 if specification.label in {"repo-policy", "uv-lock"} else 0
        return ProcessResult(specification.label, code, "", "", 0.001)

    monkeypatch.setattr(
        "tools.local_execution.capabilities.doctor_command", failing_doctor
    )
    context = CommandContext(repository.root, repository.profile, repository.uv)
    result = dispatch(Capability.DIAGNOSE, context, runner)
    output = capsys.readouterr().out
    assert_equal(result, 1, "diagnose exit")
    assert_equal(
        calls,
        ["repo-policy", "execution-architecture", "uv-lock", "coordination-state"],
        "non-fail-fast diagnostic calls",
    )
    assert_contains("COMPLETE_NOT_PROOF", output, "diagnose output")
    assert_contains("required_findings=PRESENT", output, "diagnose output")


@scenario("LF-N17", "Separate check, evidence and render outcomes")
def verify_check_evidence_render_separation(
    repository: LocalExecutionFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    def runner(specification: ProcessSpec, root: Path) -> ProcessResult:
        del root
        calls.append(specification.label)
        return ProcessResult(specification.label, 1, "", "intentional", 0.001)

    context = CommandContext(repository.root, repository.profile, repository.uv)
    result = dispatch(Capability.VERIFY, context, runner)
    output = capsys.readouterr().out
    assert_equal(result, 1, "verify exit")
    assert_equal(calls, ["repo-policy"], "fail-fast engineering calls")
    assert_contains("engineering_check=FAIL", output, "verify output")
    assert_contains("evidence_capture=NOT_RUN", output, "verify output")
    assert_contains("report_render=NOT_RUN", output, "verify output")


@scenario("LF-N18", "Bound diagnostics and forbid global mutation")
def verify_diagnostic_bounding(repository: LocalExecutionFixture) -> None:
    specification = ProcessSpec(
        "large-output",
        (sys.executable, "-c", "print('x' * 30000)"),
    )
    with step_context("Run an oversized diagnostic command"):
        result = run_process(specification, repository.root)
        attach_text("bounded stdout", result.stdout)
    assert_true(result.passed, "large output command")
    assert_contains("TRUNCATED", result.stdout, "bounded stdout")
    assert_true(len(result.stdout.encode("utf-8")) < 13_000, "bounded stdout size")
    _assert_no_global_mutation_or_dynamic_plugins(repository)


def _assert_no_global_mutation_or_dynamic_plugins(
    repository: LocalExecutionFixture,
) -> None:
    paths: Sequence[Path] = (
        repository.root / "flare",
        *sorted((repository.root / "tools/local_execution").glob("*.py")),
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for forbidden in (
        "sudo ",
        "apt install",
        "pip install",
        ".bashrc",
        "importlib.import_module",
        "entry_points(",
        "--allow-insecure-host",
        "--trusted-host",
        "http://",
        "Any",
        "dict[str, object]",
        "type: ignore",
        "noqa",
        "cast(",
        "unittest",
        "argparse",
    ):
        assert_not_contains(forbidden, source, "Local-First source")
