import sys
from pathlib import Path

from tools.local_execution.process import ProcessSpec, run_process
from tools.quality.test_architecture_policy import (
    TestRule,
    scan_repository,
    scan_test_source,
)
from tools.quality.tests.quality_hardening.architecture_fixtures import (
    ARCHITECTURE_CASES,
)
from tools.quality.tests.quality_hardening.assertions import (
    check_contains,
    check_equal,
)
from tools.quality.tests.quality_hardening.reporting import reported, step
from tools.quality.tests.quality_hardening.scenario_catalog import QH_N10
from tools.quality.tests.quality_hardening.support import (
    REPO_ROOT,
    QualityWorkspace,
    RepositoryPolicyFixture,
)


def _symlink_test_path(root: Path, target: Path) -> Path:
    path = root / "tools/quality/tests/quality_hardening/test_leak.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)
    return path


def _verify_assertions_survive_optimization() -> None:
    cases = (
        ("equal", "check_equal(1, 2, 'equal')"),
        ("contains", "check_contains('missing', 'value', 'contains')"),
        ("not-contains", "check_not_contains('present', 'present', 'not')"),
    )
    imports = (
        "from tools.quality.tests.quality_hardening.assertions import "
        "check_contains, check_equal, check_not_contains; "
    )
    for label, operation in cases:
        result = run_process(
            ProcessSpec(
                f"optimized-assertion-{label}",
                (sys.executable, "-O", "-c", f"{imports}{operation}"),
            ),
            REPO_ROOT,
        )
        check_equal(result.returncode, 1, f"код optimized assertion {label}")
        check_contains("AssertionError", result.stderr, f"ошибка {label}")


@reported(QH_N10)
def verify_test_architecture_green_and_red(workspace: QualityWorkspace) -> None:
    for case in ARCHITECTURE_CASES:
        with step(f"Проверить fixture архитектуры тестов: {case.label}"):
            violations = scan_test_source(case.source, case.path)
            observed = tuple(item.rule for item in violations)
            check_equal(
                observed,
                case.expected_rules,
                f"правила для fixture {case.label}",
            )
    with step("Исключить cache и vendor из no-Git discovery"):
        excluded = (
            workspace.root / ".cache/package/tests/test_vendor.py",
            workspace.root / "vendor/package/tests/test_vendor.py",
        )
        for path in excluded:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("def test_vendor():\n    assert True\n", encoding="utf-8")
        check_equal(scan_repository(workspace.root), (), "нарушения excluded source")
    with step("Отклонить внешний test symlink без Git metadata"):
        no_git = workspace.root / "test-symlink-no-git"
        no_git.mkdir()
        outside = workspace.root / "outside-no-git.py"
        outside.write_text("def test_external():\n    return None\n", encoding="utf-8")
        _symlink_test_path(no_git, outside)
        no_git_rules = tuple(item.rule for item in scan_repository(no_git))
        check_equal(
            no_git_rules,
            (TestRule.FILE_BOUNDARY,),
            "правила внешнего no-Git test symlink",
        )
    with step("Отклонить tracked внешний test symlink"):
        git_fixture = RepositoryPolicyFixture.create(
            workspace.root / "test-symlink-git"
        )
        outside = workspace.root / "outside-git.py"
        outside.write_text("def test_external():\n    return None\n", encoding="utf-8")
        link = _symlink_test_path(git_fixture.root, outside)
        git_fixture.require_git("add", link.relative_to(git_fixture.root).as_posix())
        git_rules = tuple(item.rule for item in scan_repository(git_fixture.root))
        check_equal(
            git_rules,
            (TestRule.FILE_BOUNDARY,),
            "правила внешнего tracked test symlink",
        )
    with step("Сохранить assertion-проверки при Python optimization"):
        _verify_assertions_survive_optimization()
