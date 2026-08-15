import os
import shlex
import shutil
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
from tools.quality.tests.local_execution.support import (
    LocalExecutionFixture,
    _publish_fixture_stage0_state,
)


def _run_stage0(
    repository: LocalExecutionFixture,
    *arguments: str,
    path: str,
    uv: Path | None = None,
    extra_environment: dict[str, str] | None = None,
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
    environment.update(extra_environment or {})
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
    marker = repository.root / "path-uv-executed"
    poisoned_uv = poison / "uv"
    poisoned_uv.write_text(
        f"#!/bin/sh\nprintf executed > {marker}\nprintf 'uv 0.12.3 (poison)\\n'\n",
        encoding="utf-8",
    )
    poisoned_uv.chmod(0o755)
    implicit = _run_stage0(
        repository,
        "bootstrap",
        path=f"{poison}:/usr/bin:/bin",
    )
    poisoned_uv.write_text(
        "#!/bin/sh\nprintf 'uv 0.0.0 (poison)\\n'\n", encoding="utf-8"
    )
    wrong = _run_stage0(
        repository,
        "bootstrap",
        path=f"{poison}:/usr/bin:/bin",
        uv=poisoned_uv,
    )
    poisoned_uv.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = --version ]; then printf 'uv 0.12.3 (poison)\\n'; "
        "else exit 73; fi\n",
        encoding="utf-8",
    )
    plausible = _run_stage0(
        repository,
        "bootstrap",
        path=f"{poison}:/usr/bin:/bin",
        uv=poisoned_uv,
    )
    assert_equal(implicit.returncode, 1, "implicit PATH uv exit")
    assert_contains("FLARE_HOST_UV", implicit.stderr, "explicit uv diagnostic")
    assert_false(marker.exists(), "implicit PATH uv execution")
    assert_equal(wrong.returncode, 1, "wrong uv version exit")
    assert_contains("wrong uv identity/version", wrong.stderr, "wrong uv diagnostic")
    assert_equal(plausible.returncode, 1, "plausible but unusable uv exit")
    assert_contains(
        "locked environment reconstruction failed",
        plausible.stdout,
        "unusable uv diagnostic",
    )
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
    assert_equal(source.count('"$MANAGED_PYTHON" -I -B -S'), 2, "sealed Python flags")


@scenario(
    "LF-STAGE0-003",
    "Reconstruct an unsealed managed Python before its first execution",
)
def verify_stage0_managed_python_reconstruction(
    repository: LocalExecutionFixture,
) -> None:
    marker = repository.root / "managed-python-canary-executed"
    repository.managed_python.write_text(
        "#!/bin/sh\nprintf executed > " + f"{marker}\nexit 96\n",
        encoding="utf-8",
    )
    repository.managed_python.chmod(0o755)
    result = _run_stage0(
        repository,
        "bootstrap",
        path="/usr/bin:/bin",
        uv=repository.uv,
    )
    assert_equal(result.returncode, 0, "managed-Python reconstruction exit")
    assert_contains("action=CREATED", result.stdout, "managed-Python bootstrap")
    assert_false(marker.exists(), "unsealed managed Python execution")


@scenario("LF-STAGE0-004", "Seal every importable managed-Python byte")
def verify_stage0_managed_tree_reconstruction(
    repository: LocalExecutionFixture,
) -> None:
    trigger = repository.root / ".flare/local-execution/python/execute-canary"
    trigger.write_text("unsealed tree member\n", encoding="ascii")
    result = _run_stage0(
        repository,
        "bootstrap",
        path="/usr/bin:/bin",
        uv=repository.uv,
    )
    marker = repository.root / "managed-python-executed"
    assert_equal(result.returncode, 0, "managed-tree reconstruction exit")
    assert_false(trigger.exists(), "unsealed managed-tree member removal")
    assert_false(marker.exists(), "unsealed managed-tree execution")


@scenario("LF-STAGE0-005", "Ignore shell startup and caller locale state")
def verify_stage0_shell_isolation(repository: LocalExecutionFixture) -> None:
    startup = repository.root / "hostile-bash-env"
    marker = repository.root / "bash-env-executed"
    startup.write_text(f"printf executed > {marker}\n", encoding="utf-8")
    result = _run_stage0(
        repository,
        "bootstrap",
        path="/usr/bin:/bin",
        uv=repository.uv,
        extra_environment={"BASH_ENV": str(startup), "LC_ALL": "C"},
    )
    assert_equal(result.returncode, 0, "shell-isolated bootstrap exit")
    assert_false(marker.exists(), "shell startup execution")


@scenario("LF-STAGE0-006", "Reject externally aliased managed-tree files")
def verify_stage0_managed_tree_hardlink(
    repository: LocalExecutionFixture,
) -> None:
    alias = repository.root / "managed-python-external-alias"
    os.link(repository.managed_python, alias)
    result = _run_stage0(
        repository,
        "bootstrap",
        path="/usr/bin:/bin",
        uv=repository.uv,
    )
    assert_equal(result.returncode, 1, "hardlinked managed-tree exit")
    assert_contains("unsafe to reconstruct", result.stderr, "hardlink diagnostic")
    assert_equal(
        alias.read_bytes(), repository.managed_python.read_bytes(), "alias bytes"
    )


@scenario("LF-STAGE0-007", "Reject an external intermediate Stage-0 root")
def verify_stage0_root_confinement(repository: LocalExecutionFixture) -> None:
    outside = repository.root.parent / "external-stage0-state"
    marker = repository.root / "external-managed-python-executed"
    (repository.root / ".venv").mkdir(mode=0o700)
    shutil.move(repository.root / ".flare", outside)
    (repository.root / ".flare").symlink_to(outside, target_is_directory=True)
    external_python = outside / repository.managed_python.relative_to(
        repository.root / ".flare"
    )
    external_python.write_text(
        f"#!/bin/sh\nprintf executed > {marker}\nexit 97\n",
        encoding="utf-8",
    )
    external_python.chmod(0o755)
    _publish_fixture_stage0_state(repository.root)
    result = _run_stage0(
        repository,
        "doctor",
        path="/usr/bin:/bin",
        uv=repository.uv,
    )
    assert_equal(result.returncode, 1, "external Stage-0 root exit")
    assert_contains("Stage-0 directory", result.stderr, "root confinement diagnostic")
    assert_false(marker.exists(), "external managed Python execution")


def _poison_fake_uv_find(repository: LocalExecutionFixture) -> tuple[Path, Path]:
    invoked = repository.root / "uv-find-invoked"
    executed = repository.root / "uv-find-canary-executed"
    canary = repository.root / "uv-find-canary"
    canary.write_text(
        f"#!/bin/sh\nprintf executed > {shlex.quote(str(executed))}\nexit 97\n",
        encoding="utf-8",
    )
    canary.chmod(0o755)
    uv_source = repository.uv.read_text(encoding="utf-8")
    managed = repository.managed_python
    original = f"      find) printf '%s\\n' {shlex.quote(str(managed))} ;;"
    poisoned = (
        f"      find) printf invoked > {shlex.quote(str(invoked))}; "
        f"{shlex.quote(str(canary))} ;;"
    )
    assert_contains(original, uv_source, "fake uv find branch")
    repository.uv.write_text(uv_source.replace(original, poisoned), encoding="utf-8")
    repository.uv.chmod(0o755)
    return invoked, executed


def _assert_uv_find_not_invoked(markers: tuple[Path, Path], label: str) -> None:
    for marker in markers:
        assert_false(marker.exists(), f"{label}: {marker.name}")


def _make_fake_uv_install_duplicate(repository: LocalExecutionFixture) -> Path:
    uv_source = repository.uv.read_text(encoding="utf-8")
    managed = repository.managed_python
    marker = repository.root / "duplicate-managed-python-executed"
    payload = f"#!/bin/sh\nprintf executed > {shlex.quote(str(marker))}\nexit 95\n"
    original = f"        /usr/bin/chmod 755 {shlex.quote(str(managed))}\n        ;;"
    duplicate = (
        managed.parents[2]
        / (
            f"{repository.profile.python_implementation}-"
            f"{repository.profile.python_version}-duplicate/bin"
        )
        / managed.name
    )
    replacement = (
        f"        /usr/bin/chmod 755 {shlex.quote(str(managed))}\n"
        f"        printf '%s' {shlex.quote(payload)} > {shlex.quote(str(managed))}\n"
        f"        /usr/bin/mkdir -p {shlex.quote(str(duplicate.parent))}\n"
        f"        /usr/bin/cp -- {shlex.quote(str(managed))} "
        f"{shlex.quote(str(duplicate))}\n"
        "        ;;"
    )
    assert_contains(original, uv_source, "fake uv install branch")
    repository.uv.write_text(uv_source.replace(original, replacement), encoding="utf-8")
    repository.uv.chmod(0o755)
    return marker


def _move_to_stale_installation(repository: LocalExecutionFixture) -> Path:
    stale_marker = repository.root / "stale-managed-python-executed"
    stale_installation = (
        repository.managed_python.parents[2]
        / f"{repository.profile.python_implementation}-3.14.6-linux-x86_64-gnu"
    )
    shutil.move(repository.managed_python.parents[1], stale_installation)
    stale_python = stale_installation / "bin" / repository.managed_python.name
    stale_python.write_text(
        f"#!/bin/sh\nprintf executed > {shlex.quote(str(stale_marker))}\nexit 96\n",
        encoding="utf-8",
    )
    stale_python.chmod(0o755)
    _publish_fixture_stage0_state(repository.root)
    return stale_marker


def _replace_with_unadmitted_environment(repository: LocalExecutionFixture) -> Path:
    environment = repository.root / repository.profile.project_environment
    shutil.rmtree(environment)
    state = repository.root / repository.profile.project_state
    for name in ("environment-admission-v1.json", "environment-admission-v1.sha256"):
        (state / name).unlink()
    project_marker = repository.root / "project-python-executed"
    project_python = environment / "bin/python"
    project_python.parent.mkdir(parents=True, mode=0o700)
    project_python.write_text(
        f"#!/bin/sh\nprintf executed > {shlex.quote(str(project_marker))}\nexit 98\n",
        encoding="utf-8",
    )
    project_python.chmod(0o755)
    return project_marker


@scenario("LF-STAGE0-008", "Never ask uv to inspect a managed Python candidate")
def verify_stage0_uv_managed_python_isolation(
    repository: LocalExecutionFixture,
) -> None:
    source = (repository.root / "flare").read_text(encoding="utf-8")
    assert_false("python find" in source, "uv Python discovery in Stage-0")
    uv_find_markers = _poison_fake_uv_find(repository)
    reused = _run_stage0(
        repository,
        "bootstrap",
        path="/usr/bin:/bin",
        uv=repository.uv,
    )
    _assert_uv_find_not_invoked(uv_find_markers, "sealed-tree uv find")
    assert_equal(reused.returncode, 0, "sealed managed-Python reuse exit")

    unsealed_marker = repository.root / "unsealed-managed-python-executed"
    repository.managed_python.write_text(
        f"#!/bin/sh\nprintf executed > {shlex.quote(str(unsealed_marker))}\nexit 99\n",
        encoding="utf-8",
    )
    repository.managed_python.chmod(0o755)
    reconstructed = _run_stage0(
        repository,
        "bootstrap",
        path="/usr/bin:/bin",
        uv=repository.uv,
    )
    _assert_uv_find_not_invoked(uv_find_markers, "reconstruction uv find")
    assert_false(unsealed_marker.exists(), "unsealed managed-Python execution")
    assert_equal(reconstructed.returncode, 0, "managed-Python reconstruction exit")

    project_marker = _replace_with_unadmitted_environment(repository)
    for command in ("doctor", "check-fast"):
        result = _run_stage0(
            repository,
            command,
            path="/usr/bin:/bin",
            uv=repository.uv,
        )
        assert_equal(result.returncode, 1, f"unadmitted {command} exit")
        _assert_uv_find_not_invoked(uv_find_markers, f"unadmitted {command} uv find")
        assert_false(project_marker.exists(), f"unadmitted {command} project Python")

    stale_marker = _move_to_stale_installation(repository)
    stale = _run_stage0(
        repository,
        "doctor",
        path="/usr/bin:/bin",
        uv=repository.uv,
    )
    _assert_uv_find_not_invoked(uv_find_markers, "stale-layout uv find")
    assert_false(stale_marker.exists(), "stale managed-Python execution")
    assert_equal(stale.returncode, 1, "stale managed-Python layout exit")
    assert_contains(
        "pinned managed Python is unavailable", stale.stderr, "stale layout"
    )

    duplicate_marker = _make_fake_uv_install_duplicate(repository)
    duplicate = _run_stage0(
        repository,
        "bootstrap",
        path="/usr/bin:/bin",
        uv=repository.uv,
    )
    _assert_uv_find_not_invoked(uv_find_markers, "duplicate-layout uv find")
    assert_false(duplicate_marker.exists(), "duplicate managed-Python execution")
    assert_equal(duplicate.returncode, 1, "duplicate managed-Python layout exit")
    assert_contains(
        "one safe pinned managed Python", duplicate.stderr, "duplicate layout"
    )
