from dataclasses import dataclass

from tools.quality.tests.quality_hardening.assertions import (
    check_contains,
    check_process,
)
from tools.quality.tests.quality_hardening.reporting import reported, step
from tools.quality.tests.quality_hardening.scenario_catalog import (
    QH_N05,
    QH_N06,
)
from tools.quality.tests.quality_hardening.support import QualityWorkspace, run_gitlint


@dataclass(frozen=True, slots=True)
class CommitCase:
    label: str
    message: str
    diagnostic: str = ""


_GREEN_CASES = (
    CommitCase("scoped", "feat(frontend): establish dependency graph\n"),
    CommitCase("unscoped", "fix: preserve exact candidate identity\n"),
    CommitCase("title-only", "docs(quality): describe the commit contract\n"),
    CommitCase(
        "optional-body",
        "refactor(quality): split policy audit\n\n"
        "Keep each signal independently testable.\n",
    ),
)
_RED_CASES = (
    CommitCase("unknown-type", "unknown: reject type\n", "Title does not match regex"),
    CommitCase("malformed", "quality please pass\n", "Title does not match regex"),
    CommitCase("title-73", f"fix: {'x' * 68}\n", "Title exceeds max length (73>72)"),
    CommitCase(
        "missing-separator",
        "fix: preserve contract\nbody without separator\n",
        "Second line is not empty",
    ),
    CommitCase(
        "body-73",
        f"fix: preserve contract\n\n{'x' * 73}\n",
        "Line exceeds max length (73>72)",
    ),
    CommitCase(
        "title-whitespace",
        "fix: preserve contract \n",
        "Title has trailing whitespace",
    ),
    CommitCase(
        "body-whitespace",
        "fix: preserve contract\n\nbody has trailing whitespace \n",
        "Line has trailing whitespace",
    ),
    CommitCase(
        "title-tab",
        "fix: preserve\tcontract\n",
        "Title contains hard tab characters",
    ),
    CommitCase(
        "body-tab",
        "fix: preserve contract\n\nbody\tcontains a hard tab\n",
        "Line contains hard tab characters",
    ),
)


@reported(QH_N05)
def verify_commit_message_green(workspace: QualityWorkspace) -> None:
    for case in _GREEN_CASES:
        with step(f"Принять commit message: {case.label}"):
            result = run_gitlint(workspace.root, case.message)
            check_process(result, 0, f"{case.label} gitlint")


@reported(QH_N06)
def verify_commit_message_red(workspace: QualityWorkspace) -> None:
    for case in _RED_CASES:
        with step(f"Отклонить commit message: {case.label}"):
            result = run_gitlint(workspace.root, case.message)
            output = result.stdout + result.stderr
            check_process(result, 1, f"{case.label} gitlint")
            check_contains(case.diagnostic, output, f"{case.label} diagnostic")
