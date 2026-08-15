import shutil
import sys

from tools.local_execution.doctor import doctor_command
from tools.local_execution.process import (
    CommandContext,
    ProcessRunner,
    ProcessSpec,
    run_specs,
)


def _python_spec(label: str, *arguments: str) -> ProcessSpec:
    return ProcessSpec(label, (sys.executable, *arguments))


def _repo_policy() -> ProcessSpec:
    return _python_spec("repo-policy", "tools/quality/check_repo_policy.py")


def _source_policy() -> ProcessSpec:
    return _python_spec("source-policy", "-m", "tools.quality.source_policy")


def _test_architecture_policy() -> ProcessSpec:
    return _python_spec(
        "test-architecture-policy",
        "-m",
        "tools.quality.test_architecture_policy",
    )


def _architecture() -> ProcessSpec:
    return _python_spec(
        "execution-architecture", "-m", "tools.local_execution.architecture"
    )


def _state_check() -> ProcessSpec:
    return _python_spec(
        "coordination-state",
        "-m",
        "tools.project_state.cli",
        "check",
        "--repo",
        ".",
        "--tree",
        "HEAD",
    )


def _uv_lock(context: CommandContext) -> ProcessSpec:
    return ProcessSpec(
        "uv-lock",
        (str(context.uv), "--no-config", "lock", "--check"),
        (
            (
                "UV_CACHE_DIR",
                str(context.profile.path(context.root, context.profile.uv_cache)),
            ),
        ),
    )


def _ruff_format() -> ProcessSpec:
    return _python_spec(
        "ruff-format",
        "-m",
        "ruff",
        "format",
        "--check",
        ".",
    )


def _ruff_check() -> ProcessSpec:
    return _python_spec(
        "ruff-check",
        "-m",
        "ruff",
        "check",
        "--config",
        "tools/quality/ruff-lint.toml",
        ".",
    )


def _mypy() -> ProcessSpec:
    return ProcessSpec(
        "mypy-strict",
        (
            sys.executable,
            "-I",
            "-B",
            "-m",
            "mypy",
            "--config-file=/dev/null",
            "--strict",
            "--python-version=3.14",
            "--explicit-package-bases",
            "tools",
            "typings",
        ),
        (("MYPYPATH", "typings"),),
    )


def _bundle_tests() -> ProcessSpec:
    return _python_spec(
        "dependency-bundle-tests",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "tools/quality/tests/quality_hardening/test_dependency_bundle_integrity.py",
    )


def _bundle_smoke() -> ProcessSpec:
    return ProcessSpec(
        "dependency-bundle-shell-smoke",
        (
            "/usr/bin/bash",
            "tools/platform/dependency_bundles/tests/smoke_fake_toolchain.sh",
        ),
        (
            ("FLARE_BUNDLE_PYTHON", sys.executable),
            ("PATH", "/usr/bin:/bin"),
        ),
    )


def _quality_tests() -> ProcessSpec:
    return _python_spec(
        "quality-tests",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "-n",
        "4",
        "--dist",
        "worksteal",
        "tools/quality/tests",
    )


def _quality_allure(context: CommandContext) -> ProcessSpec:
    results = context.root / ".tmp/quality-hardening-allure-results"
    return ProcessSpec(
        "quality-hardening-evidence",
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--alluredir",
            str(results),
            "--clean-alluredir",
            "--allure-no-capture",
            "tools/quality/tests/quality_hardening",
        ),
    )


def _quality_allure_audit(context: CommandContext) -> ProcessSpec:
    return _python_spec(
        "quality-hardening-evidence-audit",
        "-m",
        "tools.quality.tests.quality_hardening.allure_audit",
        str(context.root / ".tmp/quality-hardening-allure-results"),
    )


def _local_execution_tests() -> ProcessSpec:
    return _python_spec(
        "local-execution-tests",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "tools/quality/tests/local_execution",
    )


def _local_execution_allure(context: CommandContext) -> ProcessSpec:
    results = context.root / ".tmp/local-first-allure-results"
    return ProcessSpec(
        "local-execution-evidence",
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-n",
            "4",
            "--dist",
            "worksteal",
            "--alluredir",
            str(results),
            "--clean-alluredir",
            "--allure-no-capture",
            "tools/quality/tests/local_execution",
        ),
        (("FLARE_LOCAL_ALLURE_RESULTS", str(results)),),
    )


def _local_runtime_evidence(context: CommandContext) -> ProcessSpec:
    return _python_spec(
        "local-runtime-evidence",
        "-m",
        "tools.quality.tests.project_state.runtime_evidence",
        str(context.root / ".tmp/local-first-allure-results"),
        "--repo",
        str(context.root),
        "--configured-workers",
        "4",
        "--configured-distribution",
        "worksteal",
    )


def _clean_room_proof(context: CommandContext) -> ProcessSpec:
    # Each checkout has five sequential commands with a 1,200-second leaf cap;
    # the two checkouts run concurrently. Keep one bounded minute for setup,
    # manifests, compaction, and the supervisor handshake.
    return ProcessSpec(
        "clean-room-proof",
        (
            sys.executable,
            "-m",
            "tools.local_execution.clean_room",
            str(context.root / ".tmp/local-first-clean-room"),
            str(context.uv),
        ),
        timeout_seconds=6_060,
    )


def _state_tests() -> ProcessSpec:
    return _python_spec(
        "state-tests",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "-n",
        "4",
        "--dist",
        "worksteal",
        "tools/quality/tests/project_state",
    )


def _state_allure(context: CommandContext) -> ProcessSpec:
    results = context.root / ".tmp/allure-results"
    return ProcessSpec(
        "state-allure-evidence",
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-n",
            "4",
            "--dist",
            "worksteal",
            "--alluredir",
            str(results),
            "--clean-alluredir",
            "--allure-no-capture",
            "tools/quality/tests/project_state",
        ),
        (("FLARE_ALLURE_RESULTS", str(results)),),
    )


def _runtime_evidence(context: CommandContext) -> ProcessSpec:
    return _python_spec(
        "runtime-evidence",
        "-m",
        "tools.quality.tests.project_state.runtime_evidence",
        str(context.root / ".tmp/allure-results"),
        "--repo",
        str(context.root),
        "--configured-workers",
        "4",
        "--configured-distribution",
        "worksteal",
    )


def _allure_audit(context: CommandContext) -> ProcessSpec:
    return _python_spec(
        "allure-audit",
        "-m",
        "tools.quality.tests.project_state.allure_audit",
        str(context.root / ".tmp/allure-results"),
    )


def doctor(context: CommandContext, runner: ProcessRunner) -> int:
    del runner
    return doctor_command(context.root, context.profile, context.uv)


def check_fast(context: CommandContext, runner: ProcessRunner) -> int:
    return run_specs(
        context,
        runner,
        (
            _repo_policy(),
            _architecture(),
            _ruff_check(),
            _local_execution_tests(),
        ),
        fail_fast=True,
    )


def state_check(context: CommandContext, runner: ProcessRunner) -> int:
    return run_specs(context, runner, (_state_check(),), fail_fast=True)


def state_static(context: CommandContext, runner: ProcessRunner) -> int:
    return run_specs(
        context,
        runner,
        (_ruff_format(), _ruff_check(), _mypy()),
        fail_fast=True,
    )


def state_test(context: CommandContext, runner: ProcessRunner) -> int:
    return run_specs(context, runner, (_state_tests(),), fail_fast=True)


def check(context: CommandContext, runner: ProcessRunner) -> int:
    specifications = (
        _repo_policy(),
        _architecture(),
        _uv_lock(context),
        _state_check(),
        _ruff_format(),
        _ruff_check(),
        _mypy(),
        _quality_tests(),
    )
    return run_specs(context, runner, specifications, fail_fast=True)


def state_allure(context: CommandContext, runner: ProcessRunner) -> int:
    return run_specs(
        context,
        runner,
        (_state_allure(context), _runtime_evidence(context), _allure_audit(context)),
        fail_fast=True,
    )


def verify(context: CommandContext, runner: ProcessRunner) -> int:
    if check(context, runner) != 0:
        print("engineering_check=FAIL evidence_capture=NOT_RUN report_render=NOT_RUN")
        return 1
    bundle_evidence = run_specs(
        context,
        runner,
        (_bundle_tests(), _bundle_smoke()),
        fail_fast=True,
    )
    if bundle_evidence != 0:
        print("engineering_check=PASS bundle_integrity=FAIL evidence_capture=NOT_RUN")
        return 1
    quality_evidence = run_specs(
        context,
        runner,
        (_quality_allure(context), _quality_allure_audit(context)),
        fail_fast=True,
    )
    if quality_evidence != 0:
        print("engineering_check=PASS evidence_capture=FAIL report_render=NOT_RUN")
        return 1
    reproducibility = run_specs(
        context, runner, (_clean_room_proof(context),), fail_fast=True
    )
    if reproducibility != 0:
        print(
            "engineering_check=PASS reproducibility=FAIL "
            "evidence_capture=NOT_RUN report_render=NOT_RUN"
        )
        return 1
    local_evidence = run_specs(
        context,
        runner,
        (_local_execution_allure(context), _local_runtime_evidence(context)),
        fail_fast=True,
    )
    if local_evidence != 0:
        print("engineering_check=PASS evidence_capture=FAIL report_render=NOT_RUN")
        return 1
    evidence = state_allure(context, runner)
    if evidence != 0:
        print("engineering_check=PASS evidence_capture=FAIL report_render=NOT_RUN")
        return 1
    print("engineering_check=PASS evidence_capture=PASS report_render=NOT_RUN")
    return 0


def quality_advisory(context: CommandContext, runner: ProcessRunner) -> int:
    return run_specs(
        context,
        runner,
        (_source_policy(), _test_architecture_policy()),
        fail_fast=False,
    )


def diagnose(context: CommandContext, runner: ProcessRunner) -> int:
    doctor_result = doctor_command(context.root, context.profile, context.uv)
    diagnostics = run_specs(
        context,
        runner,
        (
            _repo_policy(),
            _architecture(),
            _ruff_check(),
            _uv_lock(context),
            _state_check(),
        ),
        fail_fast=False,
    )
    failed = doctor_result != 0 or diagnostics != 0
    print(
        "diagnose=COMPLETE_NOT_PROOF "
        f"required_findings={'PRESENT' if failed else 'NONE'}"
    )
    return 1 if failed else 0


def state_allure_open(context: CommandContext, runner: ProcessRunner) -> int:
    evidence = state_allure(context, runner)
    if evidence != 0:
        print("report_render=NOT_RUN engineering evidence failed")
        return 1
    allure = shutil.which("allure")
    if allure is None:
        print("report_render=FAIL optional Allure CLI is unavailable")
        return 1
    specification = ProcessSpec(
        "allure-render",
        (
            allure,
            "generate",
            str(context.root / ".tmp/allure-results"),
            "--config",
            str(context.root / "tools/quality/tests/project_state/allurerc.mjs"),
            "--output",
            str(context.root / ".tmp/allure-report"),
            "--open",
            "--port",
            "5050",
        ),
    )
    return run_specs(context, runner, (specification,), fail_fast=True)
