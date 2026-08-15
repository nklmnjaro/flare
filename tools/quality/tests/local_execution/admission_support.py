from __future__ import annotations

import shlex
import subprocess
import uuid
from pathlib import Path

from tools.local_execution.bootstrap import bootstrap_environment
from tools.quality.tests.local_execution.assertions import (
    assert_contains,
    assert_equal,
    assert_true,
)
from tools.quality.tests.local_execution.support import (
    LocalExecutionFixture,
    complete_snapshot,
)


def bootstrap_fixture(repository: LocalExecutionFixture) -> None:
    result = bootstrap_environment(
        repository.root,
        repository.profile,
        repository.uv,
        repository.managed_python,
    )
    assert_true(result.passed, "admission fixture bootstrap")


def flare_environment(
    repository: LocalExecutionFixture,
    path: str = "/usr/bin:/bin",
    extra_environment: dict[str, str] | None = None,
) -> dict[str, str]:
    environment = {
        "FLARE_HOST_UV": str(repository.uv),
        "HOME": str(repository.root / "isolated-home"),
        "LANG": "C.UTF-8",
        "PATH": path,
        "PYTHONHOME": str(repository.root / "poison-python-home"),
        "PYTHONPATH": str(repository.root / "poison-python-path"),
        "VIRTUAL_ENV": str(repository.root / "poison-virtual-environment"),
    }
    if extra_environment is not None:
        environment.update(extra_environment)
    return environment


def run_flare(
    repository: LocalExecutionFixture,
    *arguments: str,
    path: str = "/usr/bin:/bin",
    extra_environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (str(repository.root / "flare"), *arguments),
        cwd=repository.root,
        env=flare_environment(repository, path, extra_environment),
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )


def assert_include_install_red(
    repository: LocalExecutionFixture,
    hook_root: Path,
) -> None:
    config = repository.root / ".git/config"
    config_before = config.read_bytes()
    hooks_before = complete_snapshot(hook_root)
    rejected = run_flare(repository, "install-hooks")
    assert_equal(rejected.returncode, 1, "included Git config installation")
    assert_contains("detail=AdmissionError", rejected.stderr, "include diagnostic")
    assert_equal(config.read_bytes(), config_before, "include Git config")
    assert_equal(complete_snapshot(hook_root), hooks_before, "include hook bytes")


def assert_symlink_git_control_red(repository: LocalExecutionFixture) -> None:
    control = repository.root / ".git"
    external = repository.root.parent / f"external-git-{uuid.uuid4().hex}"
    control.rename(external)
    control.symlink_to(external, target_is_directory=True)
    config = external / "config"
    hooks = external / "hooks"
    config_before = config.read_bytes()
    hooks_before = complete_snapshot(hooks)
    try:
        rejected = run_flare(repository, "install-hooks")
        assert_equal(rejected.returncode, 1, "symlink Git control installation")
        assert_contains("detail=AdmissionError", rejected.stderr, "symlink Git control")
        assert_equal(config.read_bytes(), config_before, "external Git config")
        assert_equal(complete_snapshot(hooks), hooks_before, "external hook bytes")
    finally:
        control.unlink()
        external.rename(control)


def plant_project_python_canary(repository: LocalExecutionFixture) -> Path:
    marker = repository.root / "project-environment-canary-executed"
    python = repository.root / repository.profile.project_environment / "bin/python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.unlink(missing_ok=True)
    python.write_text(
        "#!/bin/sh\nprintf executed > " + shlex.quote(str(marker)) + "\nexit 97\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    return marker
