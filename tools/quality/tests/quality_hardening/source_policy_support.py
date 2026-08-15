from __future__ import annotations

import sys
from pathlib import Path

from tools.local_execution.model import ProcessResult
from tools.local_execution.process import ProcessSpec, run_process
from tools.quality.tests.quality_hardening.repository_policy_support import (
    create_repository_policy_fixture,
)
from tools.quality.tests.quality_hardening.support import (
    REPO_ROOT,
    RepositoryPolicyFixture,
)


def create_source_policy_fixture(
    root: Path,
    *,
    with_git: bool = True,
) -> RepositoryPolicyFixture:
    fixture = create_repository_policy_fixture(root, with_git=with_git)
    fixture.write(
        "pyproject.toml",
        "[tool.flare.quality]\nmax-callable-lines = 80\n",
    )
    fixture.write(
        "tools/quality/ruff-lint.toml",
        "line-length = 120\n",
    )
    fixture.write("tools/quality/source_policy.py", "SOURCE_POLICY_FIXTURE = True\n")
    fixture.write(
        "tools/quality/test_architecture_policy.py",
        "TEST_POLICY_FIXTURE = True\n",
    )
    return fixture


def run_mypy_source(source: str) -> ProcessResult:
    return run_process(
        ProcessSpec(
            "mypy-suppression-fixture",
            (sys.executable, "-m", "mypy", "--strict", "-c", source),
        ),
        REPO_ROOT,
    )
