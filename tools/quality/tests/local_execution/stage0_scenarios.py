import os
import subprocess
from pathlib import Path

from tools.local_execution.bootstrap import bootstrap_environment
from tools.quality.tests.local_execution.assertions import (
    assert_contains,
    assert_equal,
    assert_false,
    assert_true,
)
from tools.quality.tests.local_execution.reporting import scenario, step_context
from tools.quality.tests.local_execution.support import LocalExecutionFixture


def _run_stage0(
    repository: LocalExecutionFixture,
    *arguments: str,
    path: str,
    uv: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = {
        "HOME": str(repository.root / "isolated-home"),
        "LANG": "C.UTF-8",
        "PATH": path,
        "PYTHONHOME": str(repository.root / "poison-python-home"),
        "PYTHONPATH": str(repository.root / "poison-python-path"),
        "VIRTUAL_ENV": str(repository.root / "poison-virtual-environment"),
    }
    if uv is not None:
        environment["FLARE_HOST_UV"] = str(uv)
    return subprocess.run(
        (str(repository.root / "flare"), *arguments),
        cwd=repository.root,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )


@scenario("LF-N19", "Reject unsupported hosts before bootstrap mutation")
def verify_stage0_unsupported_host(repository: LocalExecutionFixture) -> None:
    profile_path = repository.root / "tools/local_execution/host_profile.toml"
    original = profile_path.read_text(encoding="utf-8")
    profile_path.write_text(
        original.replace(
            'architecture = "x86_64"', 'architecture = "unsupported-fixture"'
        ),
        encoding="utf-8",
    )
    before = tuple(repository.root.rglob(".venv"))
    result = _run_stage0(
        repository,
        "bootstrap",
        path="/usr/bin:/bin",
        uv=repository.uv,
    )
    after = tuple(repository.root.rglob(".venv"))
    assert_equal(result.returncode, 1, "unsupported-host exit")
    assert_contains("unsupported host", result.stderr, "unsupported-host diagnostic")
    assert_equal(after, before, "unsupported-host project environment state")
    profile_path.write_text(
        original.replace(
            "required_host_commands = [",
            'required_host_commands = [\n  "/definitely/missing/local-first",',
        ),
        encoding="utf-8",
    )
    missing = _run_stage0(
        repository,
        "doctor",
        path="/usr/bin:/bin",
        uv=repository.uv,
    )
    assert_equal(missing.returncode, 1, "missing Stage-0 prerequisite exit")
    assert_contains(
        "required host command is missing", missing.stderr, "Stage-0 prerequisite"
    )


@scenario("LF-N20", "Reject poisoned uv identity and behavior")
def verify_stage0_poisoned_uv(repository: LocalExecutionFixture) -> None:
    poison = repository.root / "poison-bin"
    poison.mkdir()
    wrong_version = poison / "uv"
    wrong_version.write_text(
        "#!/bin/sh\nprintf 'uv 0.0.0 (poison)\\n'\n", encoding="utf-8"
    )
    wrong_version.chmod(0o755)
    wrong = _run_stage0(
        repository,
        "bootstrap",
        path=f"{poison}:/usr/bin:/bin",
    )
    wrong_version.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = --version ]; then printf 'uv 0.12.3 (poison)\\n'; "
        "else exit 73; fi\n",
        encoding="utf-8",
    )
    plausible = _run_stage0(
        repository,
        "bootstrap",
        path=f"{poison}:/usr/bin:/bin",
    )
    assert_equal(wrong.returncode, 1, "wrong uv version exit")
    assert_contains("wrong uv identity/version", wrong.stderr, "wrong uv diagnostic")
    assert_equal(plausible.returncode, 1, "plausible but unusable uv exit")
    assert_contains("failed to install", plausible.stderr, "unusable uv diagnostic")
    assert_false(
        (repository.root / repository.profile.project_environment).exists(),
        "poisoned uv cannot activate an environment",
    )


@scenario("LF-N21", "Ignore PATH Python and use the reconstructed environment")
def verify_stage0_poisoned_python(repository: LocalExecutionFixture) -> None:
    bootstrapped = bootstrap_environment(
        repository.root,
        repository.profile,
        repository.uv,
        repository.managed_python,
    )
    poison = repository.root / "poison-python"
    poison.mkdir()
    marker = repository.root / "poison-python-executed"
    for name in ("python", "python3", "python3.14"):
        target = poison / name
        target.write_text(
            f"#!/bin/sh\nprintf invoked > {marker}\nexit 93\n", encoding="utf-8"
        )
        target.chmod(0o755)
    with step_context("Run doctor with poisoned Python names first in PATH"):
        result = _run_stage0(
            repository,
            "doctor",
            path=f"{poison}:/usr/bin:/bin",
            uv=repository.uv,
        )
    assert_true(bootstrapped.passed, "poisoned-PATH fixture bootstrap")
    assert_equal(result.returncode, 0, "doctor under Python PATH poisoning")
    assert_contains("doctor=PASS", result.stdout, "doctor output")
    assert_false(marker.exists(), "poison Python execution")


@scenario("LF-N22", "Keep default bootstrap free of global mutation commands")
def verify_stage0_environment_allowlist(repository: LocalExecutionFixture) -> None:
    source = (repository.root / "flare").read_text(encoding="utf-8")
    for forbidden in (
        "sudo",
        "apt ",
        "pip install",
        "--trusted-host",
        "--native-tls",
        ".bashrc",
        ".profile",
    ):
        assert_false(forbidden in source, f"Stage-0 forbidden token {forbidden!r}")
    assert_true(os.path.isabs(str(repository.uv)), "fixture uv identity is explicit")
