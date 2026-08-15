import ast
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Final, NotRequired, TypedDict, assert_type

import pytest

from tools.local_execution import capabilities as capabilities_module
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

_EXPECTED_BLOCKING_CALLS = {
    Capability.CHECK_FAST: [
        "repo-policy",
        "execution-architecture",
        "ruff-check",
        "local-execution-tests",
    ],
    Capability.CHECK: [
        "repo-policy",
        "execution-architecture",
        "uv-lock",
        "coordination-state",
        "ruff-format",
        "ruff-check",
        "mypy-strict",
        "quality-tests",
    ],
    Capability.VERIFY: [
        "repo-policy",
        "execution-architecture",
        "uv-lock",
        "coordination-state",
        "ruff-format",
        "ruff-check",
        "mypy-strict",
        "quality-tests",
        "dependency-bundle-tests",
        "dependency-bundle-shell-smoke",
        "quality-hardening-evidence",
        "quality-hardening-evidence-audit",
        "clean-room-proof",
        "local-execution-evidence",
        "local-runtime-evidence",
        "state-allure-evidence",
        "runtime-evidence",
        "allure-audit",
    ],
    Capability.DIAGNOSE: [
        "repo-policy",
        "execution-architecture",
        "ruff-check",
        "uv-lock",
        "coordination-state",
    ],
}


class _LanguageVersions(TypedDict):
    python: str


class _Hook(TypedDict):
    id: str
    name: str
    entry: str
    language: str
    pass_filenames: NotRequired[bool]
    always_run: NotRequired[bool]
    stages: tuple[str, ...]


class _HookRepository(TypedDict):
    repo: str
    hooks: tuple[_Hook, ...]


class _HookContract(TypedDict):
    minimum_pre_commit_version: str
    default_language_version: _LanguageVersions
    fail_fast: bool
    repos: tuple[_HookRepository, ...]


_EXPECTED_HOOK_CONTRACT: Final[_HookContract] = {
    "minimum_pre_commit_version": "4.6.0",
    "default_language_version": {"python": "python3.14"},
    "fail_fast": False,
    "repos": (
        {
            "repo": "local",
            "hooks": (
                {
                    "id": "project-check-fast",
                    "name": "Canonical fast project check",
                    "entry": "./flare check-fast",
                    "language": "system",
                    "pass_filenames": False,
                    "always_run": True,
                    "stages": ("pre-commit",),
                },
                {
                    "id": "commit-message",
                    "name": "Conventional Commit contract",
                    "entry": "./flare commit-msg",
                    "language": "system",
                    "stages": ("commit-msg",),
                },
                {
                    "id": "project-check",
                    "name": "Canonical medium project check",
                    "entry": "./flare check",
                    "language": "system",
                    "pass_filenames": False,
                    "always_run": True,
                    "stages": ("pre-push",),
                },
            ),
        },
    ),
}
assert_type(_EXPECTED_HOOK_CONTRACT, _HookContract)
_HOOK_PARSE_SCRIPT = """
import json
import sys

import yaml

with open(sys.argv[1], encoding="utf-8") as stream:
    config = yaml.safe_load(stream)
print(json.dumps(config, separators=(",", ":"), sort_keys=True))
"""


def _scenario_ids(source_root: Path) -> tuple[str, ...]:
    identifiers: list[str] = []
    scenarios_root = source_root / "tools/quality/tests/local_execution"
    for path in sorted(scenarios_root.glob("*_scenarios.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                if not isinstance(decorator.func, ast.Name):
                    continue
                if decorator.func.id != "scenario" or not decorator.args:
                    continue
                identifier = decorator.args[0]
                if isinstance(identifier, ast.Constant) and isinstance(
                    identifier.value, str
                ):
                    identifiers.append(identifier.value)
    return tuple(identifiers)


def _duplicate_ids(identifiers: tuple[str, ...]) -> tuple[str, ...]:
    counts = Counter(identifiers)
    return tuple(
        sorted(identifier for identifier, count in counts.items() if count > 1)
    )


def _verify_unique_scenario_ids(source_root: Path) -> None:
    identifiers = _scenario_ids(source_root)
    assert_equal(_duplicate_ids(identifiers), (), "уникальные Local-First scenario ID")
    assert_equal(
        _duplicate_ids((*identifiers, "LF-N14")),
        ("LF-N14",),
        "intentional RED дублирующего scenario ID",
    )


@scenario(
    "LF-N14",
    "Обнаружить дублирование политики в адаптерах",
    feature="Владение командами",
)
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
    mypy = capabilities_module._mypy()
    assert_equal(mypy.argv[1:3], ("-I", "-B"), "isolated mypy interpreter")
    assert_true("--config-file=/dev/null" in mypy.argv, "isolated mypy config")
    assert_true("--strict" in mypy.argv, "command-owned mypy strictness")
    assert_equal(dict(mypy.environment).get("MYPYPATH"), "typings", "mypy path")

    hostile = repository.root / ".tmp" / "hostile-mypy-config"
    hostile.mkdir(parents=True)
    (hostile / ".mypy.ini").write_text(
        "[mypy]\nignore_errors = True\nexclude = bad.py\n",
        encoding="utf-8",
    )
    (hostile / "pyproject.toml").write_text(
        "[tool.mypy]\nstrict = false\nexclude = ['bad.py']\n",
        encoding="utf-8",
    )
    (hostile / "bad.py").write_text("value: str = 1\n", encoding="utf-8")
    shadow = hostile / "mypy"
    shadow.mkdir()
    shadow_marker = hostile / "shadow-executed"
    (shadow / "__main__.py").write_text(
        "from pathlib import Path\nPath('shadow-executed').write_text('shadowed')\n",
        encoding="utf-8",
    )
    isolated = ProcessSpec(
        "isolated-mypy-red",
        (*mypy.argv[:-2], "bad.py"),
        mypy.environment,
    )
    result = run_process(isolated, hostile)
    assert_equal(result.returncode, 1, "hostile mypy config isolation")
    assert_contains("assignment", result.stdout, "strict mypy diagnostic")
    assert_true(not shadow_marker.exists(), "candidate mypy shadow not executed")


@scenario(
    "LF-N15",
    "Отклонить неизвестные и дублирующиеся возможности",
    feature="Владение командами",
)
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


@scenario(
    "LF-N16",
    "Собрать несколько нарушений без ложного GREEN",
    feature="Владение командами",
)
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
        [
            "repo-policy",
            "execution-architecture",
            "ruff-check",
            "uv-lock",
            "coordination-state",
        ],
        "non-fail-fast diagnostic calls",
    )
    assert_contains("COMPLETE_NOT_PROOF", output, "diagnose output")
    assert_contains("required_findings=PRESENT", output, "diagnose output")


@scenario(
    "LF-N17",
    "Разделить результаты проверок, evidence и рендеринга",
    feature="Владение командами",
)
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


@scenario(
    "LF-N18",
    "Ограничить диагностику и запретить глобальные мутации",
    feature="Владение командами",
)
def verify_diagnostic_bounding(repository: LocalExecutionFixture) -> None:
    specification = ProcessSpec(
        "large-output",
        (sys.executable, "-c", "print('x' * 30000)"),
    )
    with step_context("Выполнить команду с избыточным диагностическим выводом"):
        result = run_process(specification, repository.root)
        attach_text("bounded stdout", result.stdout)
    assert_true(result.passed, "large output command")
    assert_contains("TRUNCATED", result.stdout, "bounded stdout")
    assert_true(len(result.stdout.encode("utf-8")) < 13_000, "bounded stdout size")
    _assert_no_global_mutation_or_dynamic_plugins(repository)


@scenario(
    "LF-N23",
    "Сохранить advisory-сканеры вне блокирующих команд",
    feature="Владение командами",
)
def verify_advisory_isolation(
    repository: LocalExecutionFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def healthy_doctor(root: Path, profile: HostProfile, uv: Path) -> int:
        del root, profile, uv
        return 0

    def runner(specification: ProcessSpec, root: Path) -> ProcessResult:
        del root
        calls.append(specification.label)
        return ProcessResult(specification.label, 0, "", "", 0.001)

    monkeypatch.setattr(
        "tools.local_execution.capabilities.doctor_command", healthy_doctor
    )
    context = CommandContext(repository.root, repository.profile, repository.uv)
    for capability, expected in _EXPECTED_BLOCKING_CALLS.items():
        calls.clear()
        result = dispatch(capability, context, runner)
        assert_equal(result, 0, f"{capability.value} exit")
        assert_equal(calls, expected, f"{capability.value} required leaves")

    calls.clear()
    result = dispatch(Capability.QUALITY_ADVISORY, context, runner)
    assert_equal(result, 0, "quality-advisory exit")
    assert_equal(
        calls,
        ["source-policy", "test-architecture-policy"],
        "explicit advisory calls",
    )

    source_root = Path(__file__).resolve().parents[4]
    _verify_hook_adapters(source_root)
    _verify_unique_scenario_ids(source_root)


def _verify_hook_adapters(source_root: Path) -> None:
    validated = run_process(
        ProcessSpec(
            "pre-commit-config",
            (
                sys.executable,
                "-m",
                "pre_commit",
                "validate-config",
                str(source_root / ".pre-commit-config.yaml"),
            ),
            (("PRE_COMMIT_HOME", str(source_root / ".cache/pre-commit")),),
        ),
        source_root,
    )
    assert_equal(validated.returncode, 0, "pre-commit config validation")
    parsed = run_process(
        ProcessSpec(
            "pre-commit-contract",
            (
                sys.executable,
                "-c",
                _HOOK_PARSE_SCRIPT,
                str(source_root / ".pre-commit-config.yaml"),
            ),
        ),
        source_root,
    )
    assert_equal(parsed.returncode, 0, "pre-commit contract parse")
    expected = json.dumps(
        _EXPECTED_HOOK_CONTRACT,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert_equal(parsed.stdout.strip(), expected, "exact hook adapter contract")
    hooks = (source_root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    for forbidden_hook_text in (
        "source-policy",
        "test-architecture-policy",
        "--fix",
        "--commit HEAD",
    ):
        assert_not_contains(forbidden_hook_text, hooks, "hook advisory isolation")


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
