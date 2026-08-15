from __future__ import annotations

import shutil
from pathlib import Path

from tools.quality.tests.quality_hardening.support import (
    REPO_ROOT,
    RepositoryPolicyFixture,
)


def create_repository_policy_fixture(
    root: Path,
    *,
    with_git: bool = True,
) -> RepositoryPolicyFixture:
    fixture = RepositoryPolicyFixture.create(root, with_git=with_git)
    for relative in (
        Path("tools/canonical_paths.py"),
        Path("tools/quality/repository_paths.py"),
    ):
        target = fixture.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    return fixture
