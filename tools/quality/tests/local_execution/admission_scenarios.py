from __future__ import annotations

import hashlib
import json
import math
import os
import shlex
import stat
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tools.local_execution import admission as admission_module
from tools.local_execution.admission import (
    ADMISSION_DIGEST_NAME,
    ADMISSION_NAME,
    AdmissionError,
    EnvironmentState,
    JSONValue,
    inspect_admission,
    publish_admission,
)
from tools.local_execution.bootstrap import bootstrap_environment
from tools.quality.tests.local_execution.admission_support import (
    assert_include_install_red,
    assert_symlink_git_control_red,
    bootstrap_fixture,
    flare_environment,
    plant_project_python_canary,
    run_flare,
)
from tools.quality.tests.local_execution.assertions import (
    assert_contains,
    assert_equal,
    assert_false,
    assert_not_contains,
    assert_raises,
    assert_true,
)
from tools.quality.tests.local_execution.reporting import (
    attach_text,
    scenario,
    step_context,
)
from tools.quality.tests.local_execution.support import (
    LocalExecutionFixture,
    complete_snapshot,
    create_fixture,
)

SOURCE_ROOT = Path(__file__).resolve().parents[4]


class InjectedCrash(RuntimeError):
    pass


def _inspect(repository: LocalExecutionFixture) -> EnvironmentState:
    return inspect_admission(
        repository.root,
        repository.profile,
        repository.uv,
        repository.managed_python,
    ).state


def _wait_for_path(path: Path, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {path.name}")
        time.sleep(0.01)


def _record_paths(repository: LocalExecutionFixture) -> tuple[Path, Path]:
    state = repository.root / repository.profile.project_state
    return state / ADMISSION_NAME, state / ADMISSION_DIGEST_NAME


def _rebind_record(record: Path, digest: Path, raw: bytes) -> None:
    record.write_bytes(raw)
    record.chmod(0o600)
    digest.write_text(hashlib.sha256(raw).hexdigest() + "\n", encoding="ascii")
    digest.chmod(0o600)


def _canonical(value: JSONValue) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def _json_mapping(value: JSONValue) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise TypeError("fixture JSON value is not an object")
    return value


def _poisoned_git_environment(
    repository: LocalExecutionFixture,
    attacker: Path,
) -> dict[str, str]:
    git = attacker / ".git"
    alternate = attacker / "alternate-objects"
    alternate.mkdir()
    global_config = attacker / "global.gitconfig"
    system_config = attacker / "system.gitconfig"
    global_config.touch()
    system_config.touch()
    return {
        "FLARE_HOST_UV": str(repository.uv),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(alternate),
        "GIT_CEILING_DIRECTORIES": str(repository.root.parent),
        "GIT_COMMON_DIR": str(git),
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_GLOBAL": str(global_config),
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_NOSYSTEM": "0",
        "GIT_CONFIG_SYSTEM": str(system_config),
        "GIT_CONFIG_VALUE_0": "*",
        "GIT_DIR": str(git),
        "GIT_INDEX_FILE": str(git / "index"),
        "GIT_OBJECT_DIRECTORY": str(git / "objects"),
        "GIT_WORK_TREE": str(attacker),
        "HOME": str(repository.root / "hook-home"),
        "PATH": "/usr/bin:/bin",
    }


def _git_environment(repository: LocalExecutionFixture) -> dict[str, str]:
    return {
        "FLARE_HOST_UV": str(repository.uv),
        "HOME": str(repository.root / "git-home"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
    }


def _run_git(
    repository: LocalExecutionFixture,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("/usr/bin/git", "-C", str(repository.root), *arguments),
        cwd=repository.root,
        env=_git_environment(repository),
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )


def _assert_installed_hook_payloads(hook_root: Path) -> None:
    for name in ("pre-commit", "commit-msg", "pre-push"):
        payload = (hook_root / name).read_text(encoding="utf-8")
        assert_contains('"$ROOT/flare"', payload, f"installed {name} adapter")
        assert_contains("exec /usr/bin/env -i", payload, f"installed {name} clean env")
        assert_contains("/usr/bin/git rev-parse", payload, f"installed {name} Git")
        assert_not_contains(".venv", payload, f"installed {name} bypass")


def _assert_pinned_hooks_path(
    repository: LocalExecutionFixture,
    hook_root: Path,
    configured_path: str,
) -> None:
    configured = _run_git(
        repository, "config", "--local", "core.hooksPath", configured_path
    )
    assert_equal(configured.returncode, 0, "hooks path configuration")
    installed = run_flare(repository, "install-hooks")
    assert_equal(installed.returncode, 0, "configured hooks path installation")
    _assert_pinned_hooks_value(repository, hook_root)


def _assert_pinned_hooks_value(
    repository: LocalExecutionFixture,
    hook_root: Path,
) -> None:
    configured = _run_git(repository, "config", "--local", "--get", "core.hooksPath")
    assert_equal(configured.returncode, 0, "pinned hooks path query")
    assert_equal(
        configured.stdout, str(hook_root.resolve()) + "\n", "pinned hooks path"
    )


def _assert_unsafe_hook_preflight(
    repository: LocalExecutionFixture,
    hook_root: Path,
) -> None:
    target = repository.root / "unsafe-hook-target"
    target.write_text("preserve\n", encoding="utf-8")
    hook = hook_root / "pre-commit"
    hook.symlink_to(target)
    config = repository.root / ".git/config"
    config_before = config.read_bytes()
    hooks_before = complete_snapshot(hook_root)
    rejected = run_flare(repository, "install-hooks")
    assert_equal(rejected.returncode, 1, "unsafe hook installation")
    assert_contains("detail=AdmissionError", rejected.stderr, "unsafe hook diagnostic")
    assert_equal(config.read_bytes(), config_before, "unsafe hook Git config")
    assert_equal(complete_snapshot(hook_root), hooks_before, "unsafe hook bytes")
    hook.unlink()


def _assert_worktree_config_rejected(
    repository: LocalExecutionFixture,
) -> None:
    enabled = _run_git(
        repository, "config", "--local", "extensions.worktreeConfig", "true"
    )
    assert_equal(enabled.returncode, 0, "worktree config enablement")
    configured = _run_git(
        repository, "config", "--worktree", "core.hooksPath", ".worktree-hooks"
    )
    assert_equal(configured.returncode, 0, "worktree hooks path configuration")
    git_before = complete_snapshot(repository.root / ".git")
    rejected = run_flare(repository, "install-hooks")
    assert_equal(rejected.returncode, 1, "worktree config installation")
    assert_contains(
        "detail=AdmissionError", rejected.stderr, "worktree config diagnostic"
    )
    assert_equal(
        complete_snapshot(repository.root / ".git"), git_before, "worktree RED"
    )
    assert_false((repository.root / ".worktree-hooks").exists(), "worktree hooks path")
    removed = _run_git(
        repository, "config", "--worktree", "--unset-all", "core.hooksPath"
    )
    assert_equal(removed.returncode, 0, "worktree hooks path removal")
    disabled = _run_git(
        repository, "config", "--local", "--unset-all", "extensions.worktreeConfig"
    )
    assert_equal(disabled.returncode, 0, "worktree config disablement")


def _assert_linked_include_rejected(
    repository: LocalExecutionFixture,
    hook_root: Path,
) -> None:
    linked = repository.root.parent / f"{repository.root.name}-linked"
    added = _run_git(
        repository, "worktree", "add", "-q", "-b", "include-probe", str(linked)
    )
    assert_equal(added.returncode, 0, "linked worktree creation")
    external_hooks = repository.root / "external-hooks"
    external_hooks.mkdir()
    marker = repository.root / "external-hook-ran"
    hook = external_hooks / "pre-commit"
    hook.write_text(
        "#!/bin/sh\nprintf reached > " + shlex.quote(str(marker)) + "\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    included = repository.root / "linked-hooks.conf"
    included.write_text(
        "[core]\n\thooksPath = " + str(external_hooks) + "\n",
        encoding="utf-8",
    )
    git_directory = _run_git(
        repository, "-C", str(linked), "rev-parse", "--absolute-git-dir"
    )
    assert_equal(git_directory.returncode, 0, "linked Git directory")
    condition = f"InClUdEIf.gitdir:{git_directory.stdout.strip()}.PaTh"
    configured = _run_git(
        repository, "config", "--local", "--add", condition, str(included)
    )
    assert_equal(configured.returncode, 0, "conditional include configuration")
    invoked = _run_git(repository, "-C", str(linked), "hook", "run", "pre-commit")
    assert_equal(invoked.returncode, 0, "included external hook invocation")
    assert_true(marker.exists(), "linked external hook marker")
    marker.unlink()
    assert_include_install_red(repository, hook_root)
    effective = _run_git(
        repository, "-C", str(linked), "rev-parse", "--git-path", "hooks"
    )
    assert_equal(effective.returncode, 0, "linked effective hooks path")
    assert_equal(effective.stdout, str(external_hooks) + "\n", "linked include proof")
    assert_false(marker.exists(), "external hook execution during rejected install")

    removed = _run_git(repository, "config", "--local", "--unset-all", condition)
    assert_equal(removed.returncode, 0, "conditional include removal")
    direct = "InClUdE.PaTh"
    configured = _run_git(
        repository, "config", "--local", "--add", direct, str(included)
    )
    assert_equal(configured.returncode, 0, "direct include configuration")
    included.chmod(0o000)
    assert_include_install_red(repository, hook_root)
    assert_equal(stat.S_IMODE(included.stat().st_mode), 0, "unreadable include target")
    included.chmod(0o600)
    assert_false(marker.exists(), "external hook execution during direct include RED")
    removed = _run_git(repository, "config", "--local", "--unset-all", direct)
    assert_equal(removed.returncode, 0, "direct include removal")
    pruned = _run_git(repository, "worktree", "remove", "--force", str(linked))
    assert_equal(pruned.returncode, 0, "linked worktree removal")


def _assert_git_hook_events(
    repository: LocalExecutionFixture,
    message: Path,
) -> None:
    cases = (
        ("pre-commit", ()),
        ("commit-msg", (str(message),)),
        ("pre-push", ("origin", "https://example.invalid/repository")),
    )
    for name, arguments in cases:
        result = _run_git(repository, "hook", "run", name, "--", *arguments)
        assert_equal(result.returncode, 1, f"Git-invoked {name} hook")
        assert_contains(
            "project_environment=CORRUPT REQUIRED",
            result.stderr,
            f"Git-invoked {name} admission",
        )


def _assert_poisoned_hook_invocations(
    repository: LocalExecutionFixture,
    hook_root: Path,
    message: Path,
) -> Path:
    attacker = repository.root / "hook-attacker"
    initialized = _run_git(repository, "init", "-q", str(attacker))
    assert_equal(initialized.returncode, 0, "attacker Git initialization")
    wrong_root_marker = repository.root / "wrong-hook-root-canary"
    attacker_flare = attacker / "flare"
    attacker_flare.write_text(
        "#!/bin/sh\nprintf reached > "
        + shlex.quote(str(wrong_root_marker))
        + "\nexit 91\n",
        encoding="utf-8",
    )
    attacker_flare.chmod(0o755)
    environment = _poisoned_git_environment(repository, attacker)
    for case in (
        (hook_root / "pre-commit",),
        (hook_root / "commit-msg", message),
        (hook_root / "pre-push",),
    ):
        result = subprocess.run(
            tuple(str(item) for item in case),
            cwd=repository.root,
            env=environment,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        assert_equal(result.returncode, 1, f"poisoned installed hook {case[0].name}")
        assert_contains(
            "project_environment=CORRUPT REQUIRED",
            result.stderr,
            f"correct-checkout admission {case[0].name}",
        )
    return wrong_root_marker


@scenario("A-001", "Reject a planted project Python during doctor")
def verify_planted_doctor(repository: LocalExecutionFixture) -> None:
    marker = plant_project_python_canary(repository)
    result = run_flare(repository, "doctor")
    assert_equal(result.returncode, 1, "unadmitted doctor exit")
    assert_contains("UNADMITTED", result.stderr, "unadmitted doctor diagnostic")
    assert_false(marker.exists(), "planted doctor Python execution")


@scenario("A-002", "Reject planted Python for every blocking capability")
def verify_planted_capabilities(repository: LocalExecutionFixture) -> None:
    marker = plant_project_python_canary(repository)
    commands = (
        "check-fast",
        "check",
        "verify",
        "quality-advisory",
        "diagnose",
        "environment-manifest",
        "state-check",
        "state-static",
        "state-test",
        "state-allure",
        "state-allure-open",
    )
    for command in commands:
        result = run_flare(repository, command)
        assert_equal(result.returncode, 1, f"unadmitted {command} exit")
        assert_contains("UNADMITTED", result.stderr, f"unadmitted {command}")
    assert_false(marker.exists(), "planted blocking-capability Python execution")


@scenario("A-003", "Rebuild a malicious existing environment without execution")
def verify_bootstrap_rejects_old_environment(
    repository: LocalExecutionFixture,
) -> None:
    marker = plant_project_python_canary(repository)
    result = run_flare(repository, "bootstrap")
    rejected = repository.root / repository.profile.project_state / "rejected"
    assert_equal(result.returncode, 0, "malicious-old-environment recovery")
    assert_contains("action=CREATED", result.stdout, "malicious-old-environment action")
    assert_false(marker.exists(), "old project Python execution")
    assert_true(any(rejected.iterdir()), "old environment quarantine")
    assert_equal(_inspect(repository), EnvironmentState.ADMITTED, "rebuild state")


@scenario("A-004", "Fail closed for a missing admission identity")
def verify_missing_admission(repository: LocalExecutionFixture) -> None:
    bootstrap_fixture(repository)
    record, digest = _record_paths(repository)
    digest.unlink()
    python = repository.root / repository.profile.project_environment / "bin/python"
    marker = repository.root / "missing-admission-canary"
    python.write_text(
        "#!/bin/sh\nprintf executed > " + shlex.quote(str(marker)) + "\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    assert_true(record.is_file(), "orphaned admission record fixture")
    result = run_flare(repository, "doctor")
    assert_equal(result.returncode, 1, "missing-admission exit")
    assert_false(marker.exists(), "missing-admission project Python execution")


@scenario("A-005", "Reject structurally and semantically corrupt seals")
def verify_corrupt_admission(repository: LocalExecutionFixture) -> None:
    bootstrap_fixture(repository)
    record, digest = _record_paths(repository)
    record.chmod(0o644)
    assert_equal(_inspect(repository), EnvironmentState.CORRUPT, "record mode")

    bootstrap_fixture(repository)
    record, digest = _record_paths(repository)
    valid_digest = digest.read_text(encoding="ascii").strip()
    digest.write_text(valid_digest[::-1] + "\n", encoding="ascii")
    assert_equal(_inspect(repository), EnvironmentState.CORRUPT, "reversed digest")

    bootstrap_fixture(repository)
    record, digest = _record_paths(repository)
    duplicated = b'{"schema_version":"1.0",' + record.read_bytes()[1:]
    _rebind_record(record, digest, duplicated)
    assert_equal(_inspect(repository), EnvironmentState.CORRUPT, "duplicate-key state")

    bootstrap_fixture(repository)
    record, digest = _record_paths(repository)
    value: JSONValue = json.loads(record.read_bytes())
    mapping = _json_mapping(value)
    mapping["unexpected"] = "forbidden"
    _rebind_record(record, digest, _canonical(mapping))
    assert_equal(_inspect(repository), EnvironmentState.CORRUPT, "unknown seal field")

    bootstrap_fixture(repository)
    record, digest = _record_paths(repository)
    value = json.loads(record.read_bytes())
    environment = _json_mapping(_json_mapping(value)["environment"])
    environment["uid"] = True
    _rebind_record(record, digest, _canonical(value))
    assert_equal(_inspect(repository), EnvironmentState.CORRUPT, "boolean UID state")

    bootstrap_fixture(repository)
    state = repository.root / repository.profile.project_state
    stage0 = state / "stage0-python.sha256"
    valid_stage0 = stage0.read_text(encoding="ascii").strip()
    stage0.write_text(valid_stage0 + "\nextra\n", encoding="ascii")
    assert_equal(_inspect(repository), EnvironmentState.CORRUPT, "digest framing")

    repaired = run_flare(repository, "bootstrap")
    assert_equal(repaired.returncode, 0, "Stage-0 digest repair")
    marker = (
        repository.root
        / repository.profile.project_environment
        / ".flare-environment.json"
    )
    marker.chmod(0o666)
    assert_equal(_inspect(repository), EnvironmentState.CORRUPT, "unsafe marker mode")
    bootstrap_fixture(repository)
    marker = (
        repository.root
        / repository.profile.project_environment
        / ".flare-environment.json"
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(os, "geteuid", lambda: marker.stat().st_uid + 1)
        assert_equal(_inspect(repository), EnvironmentState.CORRUPT, "foreign owner")


@scenario("A-006", "Classify changed repository configuration as stale")
def verify_stale_repository(repository: LocalExecutionFixture) -> None:
    bootstrap_fixture(repository)
    lock = repository.root / "uv.lock"
    original = lock.read_bytes()
    lock.write_bytes(original + b"\n")
    assert_equal(_inspect(repository), EnvironmentState.STALE, "changed-lock state")
    result = run_flare(repository, "doctor")
    assert_equal(result.returncode, 1, "stale environment exit")
    assert_contains("STALE", result.stderr, "stale environment diagnostic")
    lock.write_bytes(original)
    bootstrap_fixture(repository)
    repository.uv.write_bytes(repository.uv.read_bytes() + b"# replaced bytes\n")
    repository.uv.chmod(0o755)
    assert_equal(_inspect(repository), EnvironmentState.STALE, "changed uv bytes")


@scenario("A-007", "Detect project Python replacement before execution")
def verify_replaced_project_python(repository: LocalExecutionFixture) -> None:
    bootstrap_fixture(repository)
    python = repository.root / repository.profile.project_environment / "bin/python"
    marker = repository.root / "replaced-python-canary"
    python.unlink()
    python.write_text(
        "#!/bin/sh\nprintf executed > " + shlex.quote(str(marker)) + "\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    assert_equal(_inspect(repository), EnvironmentState.CORRUPT, "replaced Python")
    result = run_flare(repository, "doctor")
    assert_equal(result.returncode, 1, "replaced Python launch exit")
    assert_false(marker.exists(), "replaced project Python execution")


@scenario("A-008", "Reject a Python symlink escape and preserve its target")
def verify_python_symlink_escape(repository: LocalExecutionFixture) -> None:
    bootstrap_fixture(repository)
    external = repository.root.parent / "external-python-canary"
    external.write_text("external-canary\n", encoding="utf-8")
    external.chmod(0o755)
    expected = external.read_bytes()
    python = repository.root / repository.profile.project_environment / "bin/python"
    python.unlink()
    python.symlink_to(external)
    assert_equal(_inspect(repository), EnvironmentState.CORRUPT, "Python symlink")
    assert_equal(external.read_bytes(), expected, "external canary bytes")
    python.unlink()
    python.symlink_to("python")
    assert_equal(_inspect(repository), EnvironmentState.CORRUPT, "Python link cycle")


@scenario("A-009", "Detect changed importable package bytes")
def verify_changed_package(repository: LocalExecutionFixture) -> None:
    bootstrap_fixture(repository)
    environment = repository.root / repository.profile.project_environment
    metadata = next(
        environment.glob("lib/python3.14/site-packages/*.dist-info/METADATA")
    )
    metadata.write_bytes(metadata.read_bytes() + b"tampered\n")
    assert_equal(_inspect(repository), EnvironmentState.CORRUPT, "package mutation")


@scenario("A-010", "Detect an injected importable payload")
def verify_extra_payload(repository: LocalExecutionFixture) -> None:
    bootstrap_fixture(repository)
    environment = repository.root / repository.profile.project_environment
    payload = environment / "lib/python3.14/site-packages/injected_payload.py"
    payload.write_text("raise RuntimeError('must never import')\n", encoding="utf-8")
    assert_equal(_inspect(repository), EnvironmentState.CORRUPT, "extra payload")


@scenario("A-011", "Keep a valid admitted environment usable")
def verify_valid_admitted_environment(repository: LocalExecutionFixture) -> None:
    bootstrap_fixture(repository)
    with step_context("Проверить read-only admission перед doctor"):
        doctor = run_flare(repository, "doctor")
    with step_context("Получить манифест только после admission"):
        manifest = run_flare(repository, "environment-manifest")
    assert_equal(doctor.returncode, 0, "admitted doctor exit")
    assert_contains("doctor=PASS", doctor.stdout, "admitted doctor output")
    assert_equal(manifest.returncode, 0, "admitted manifest exit")
    assert_true(manifest.stdout.startswith("{"), "admitted manifest output")


@scenario("A-012", "Converge concurrent bootstrap to one admitted environment")
def verify_precise_concurrent_bootstrap(repository: LocalExecutionFixture) -> None:
    overlap = repository.root / "uv-install-overlap"
    installed = repository.root / "uv-install-observed"
    (repository.root / "enable-install-guard").touch()
    (repository.root / "enable-version-barrier").touch()
    state = repository.root / repository.profile.project_state
    (state / "stage0-python.sha256").write_text("0" * 64 + "\n", encoding="ascii")

    def run() -> tuple[str, str]:
        completed = run_flare(
            repository,
            "bootstrap",
        )
        assert_equal(completed.returncode, 0, "public concurrent bootstrap exit")
        pairs = tuple(
            line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line
        )
        fields = dict(pairs)
        assert_equal(len(fields), len(pairs), "unique concurrent output fields")
        action = fields.get("action")
        digest = fields.get("manifest_sha256")
        assert_true(action in {"CREATED", "REUSED"}, "concurrent action field")
        assert_true(
            digest is not None
            and len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest),
            "concurrent manifest digest field",
        )
        if action is None or digest is None:
            raise AssertionError("concurrent bootstrap omitted a required field")
        return action, digest

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: run(), range(2)))
    assert_equal(
        sorted(action for action, _ in results),
        ["CREATED", "REUSED"],
        "concurrent actions",
    )
    assert_equal(len({digest for _, digest in results}), 1, "concurrent identity")
    assert_true(installed.exists(), "managed-Python reconstruction exercised")
    assert_false(overlap.exists(), "overlapping managed-Python installation")
    assert_equal(_inspect(repository), EnvironmentState.ADMITTED, "concurrent state")


@scenario("A-013", "Fail closed at every activation and seal boundary")
def verify_activation_faults(tmp_path: Path) -> None:
    phases = (
        "after-sync",
        "after-candidate-validation",
        "before-activation",
        "after-environment-activation",
        "before-admission-publication",
        "after-admission-publication",
    )
    observed: dict[str, str] = {}
    for index, phase in enumerate(phases):
        repository = create_fixture(tmp_path / f"fault-{index}")

        def crash(current: str, *, selected: str = phase) -> None:
            if current == selected:
                raise InjectedCrash(selected)

        with pytest.raises(InjectedCrash):
            bootstrap_environment(
                repository.root,
                repository.profile,
                repository.uv,
                repository.managed_python,
                crash,
            )
        state = _inspect(repository)
        observed[phase] = state.value
        expected = (
            EnvironmentState.ADMITTED
            if phase == "after-admission-publication"
            else EnvironmentState.UNADMITTED
            if phase in {"after-environment-activation", "before-admission-publication"}
            else EnvironmentState.ABSENT
        )
        assert_equal(state, expected, f"fault state at {phase}")
    attach_text("activation fault states", json.dumps(observed, sort_keys=True))


@scenario("A-014", "Route every hook adapter through admission")
def verify_hook_admission(repository: LocalExecutionFixture) -> None:
    initialized = _run_git(repository, "init", "-q")
    assert_equal(initialized.returncode, 0, "fixture Git initialization")
    marker = plant_project_python_canary(repository)
    message = repository.root / "COMMIT_EDITMSG"
    message.write_text("feat: fixture\n", encoding="utf-8")
    commands = (
        ("commit-msg", str(message)),
        ("install-hooks",),
        ("check-fast",),
        ("check",),
    )
    for command in commands:
        result = run_flare(repository, *command)
        assert_equal(result.returncode, 1, f"hook adapter {command[0]}")
    hooks = (repository.root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert_contains("entry: ./flare commit-msg", hooks, "commit-msg adapter")
    assert_not_contains("entry: .venv", hooks, "direct environment hook")
    assert_false(marker.exists(), "hook project Python execution")

    bootstrap_fixture(repository)
    hook_root = repository.root / ".git/hooks"
    assert_symlink_git_control_red(repository)
    _assert_unsafe_hook_preflight(repository, hook_root)
    _assert_worktree_config_rejected(repository)
    _assert_linked_include_rejected(repository, hook_root)
    custom_hooks = repository.root / ".custom-hooks"
    hook_alias = repository.root / ".hook-alias"
    hook_alias.symlink_to(".git", target_is_directory=True)
    for configured_path in (".custom-hooks", ".hook-alias/hooks", ".git/hooks"):
        _assert_pinned_hooks_path(repository, hook_root, configured_path)
    assert_false(custom_hooks.exists(), "custom hooks directory creation")
    assert_true(hook_alias.is_symlink(), "hooks alias preserved")

    global_config = repository.root / "git-home/.gitconfig"
    global_config.parent.mkdir()
    global_config.write_text(
        "[core]\n\thooksPath = .global-hooks\n",
        encoding="utf-8",
    )
    unset = _run_git(repository, "config", "--local", "--unset-all", "core.hooksPath")
    assert_equal(unset.returncode, 0, "local hooks pin removal")
    installed = run_flare(repository, "install-hooks")
    assert_equal(installed.returncode, 0, "admitted hook installation")
    _assert_pinned_hooks_value(repository, hook_root)
    _assert_installed_hook_payloads(hook_root)

    poisoned = plant_project_python_canary(repository)
    _assert_git_hook_events(repository, message)
    wrong_root_marker = _assert_poisoned_hook_invocations(
        repository, hook_root, message
    )
    assert_false(poisoned.exists(), "installed-hook project Python execution")
    assert_false(wrong_root_marker.exists(), "wrong-checkout flare execution")


@scenario("A-015", "Require an explicit trusted dependency-bundle Python")
def verify_bundle_python_contract(repository: LocalExecutionFixture) -> None:
    marker = plant_project_python_canary(repository)
    scripts = repository.root / "tools/platform/dependency_bundles"
    out = repository.root / "bundle-output"
    cases = (
        (scripts / "restore_role_bundle.sh", "missing.tar.gz", str(repository.root)),
        (scripts / "accept_bundle.sh", "linter", str(repository.root), str(out)),
        (
            scripts / "flare-bundle.sh",
            "--repo",
            str(repository.root),
            "--profile",
            "linter",
            "--out",
            str(out),
        ),
    )
    environment = {"HOME": str(repository.root / "home"), "PATH": "/usr/bin:/bin"}
    for arguments in cases:
        result = subprocess.run(
            tuple(str(item) for item in arguments),
            cwd=repository.root,
            env=environment,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        assert_true(result.returncode != 0, f"bundle adapter {arguments[0].name}")
        assert_contains("FLARE_BUNDLE_PYTHON", result.stderr, "bundle diagnostic")
    assert_false(marker.exists(), "bundle fallback Python execution")


@scenario("A-017", "Ignore PATH and global Python poisoning")
def verify_global_python_poisoning(repository: LocalExecutionFixture) -> None:
    bootstrap_fixture(repository)
    poison = repository.root / "poison-bin"
    poison.mkdir()
    marker = repository.root / "global-python-canary"
    uv_marker = repository.root / "path-uv-canary"
    uv = poison / "uv"
    uv.write_text(
        "#!/bin/sh\nprintf executed > " + shlex.quote(str(uv_marker)) + "\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)
    for name in ("python", "python3", "python3.14"):
        executable = poison / name
        executable.write_text(
            "#!/bin/sh\nprintf executed > " + shlex.quote(str(marker)) + "\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
    environment_probe = repository.root / "stage1-environment-probe.json"
    result = run_flare(
        repository,
        "doctor",
        path=f"{poison}:/usr/bin:/bin",
        extra_environment={
            "PIP_EXTRA_INDEX_URL": "https://credential.invalid/simple",
            "PYTEST_ADDOPTS": "--collect-only",
            "PYTHONOPTIMIZE": "1",
            "PYTHONPATH": str(poison),
            "UV_EXTRA_INDEX_URL": "https://credential.invalid/extra",
            "UV_INDEX_URL": "https://credential.invalid/index",
            "UV_KEYRING_PROVIDER": "subprocess",
        },
    )
    assert_equal(result.returncode, 0, "PATH-poisoned doctor")
    assert_false(marker.exists(), "PATH/global Python execution")
    assert_false(uv_marker.exists(), "PATH uv execution")
    probe = json.loads(environment_probe.read_text(encoding="utf-8"))
    assert_equal(probe, {"optimize": 0, "sensitive": []}, "Stage-1 environment")


def _metadata_snapshot(root: Path) -> tuple[tuple[str, int, int, int, int], ...]:
    values: list[tuple[str, int, int, int, int]] = []
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        values.append(
            (
                path.relative_to(root).as_posix(),
                stat.S_IMODE(metadata.st_mode),
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ino,
            )
        )
    return tuple(values)


@scenario("A-018", "Keep the admission read path non-mutating")
def verify_read_only_admission(repository: LocalExecutionFixture) -> None:
    bootstrap_fixture(repository)
    environment = repository.root / repository.profile.project_environment
    state = repository.root / repository.profile.project_state
    before_bytes = complete_snapshot(environment)
    before_metadata = _metadata_snapshot(environment)
    before_state_bytes = complete_snapshot(state)
    before_state_metadata = _metadata_snapshot(state)
    inspection = inspect_admission(
        repository.root,
        repository.profile,
        repository.uv,
        repository.managed_python,
    )
    doctor = run_flare(repository, "doctor")
    after_bytes = complete_snapshot(environment)
    after_metadata = _metadata_snapshot(environment)
    after_state_bytes = complete_snapshot(state)
    after_state_metadata = _metadata_snapshot(state)
    assert_true(inspection.admitted, "read-only admission result")
    assert_equal(doctor.returncode, 0, "read-only admitted doctor")
    assert_equal(after_bytes, before_bytes, "read-only admission bytes")
    assert_equal(after_metadata, before_metadata, "read-only admission metadata")
    assert_equal(after_state_bytes, before_state_bytes, "read-only Stage-0 state bytes")
    assert_equal(
        after_state_metadata,
        before_state_metadata,
        "read-only Stage-0 state metadata",
    )


@scenario("A-019", "Measure admitted p50 and p95 without a PASS cache")
def verify_admission_performance(repository: LocalExecutionFixture) -> None:
    bootstrap_fixture(repository)
    durations: list[float] = []
    for _ in range(12):
        started = time.perf_counter()
        inspection = inspect_admission(
            repository.root,
            repository.profile,
            repository.uv,
            repository.managed_python,
        )
        durations.append(time.perf_counter() - started)
        assert_true(inspection.admitted, "timed admitted inspection")
    ordered = sorted(durations)
    p50 = ordered[math.ceil(0.50 * len(ordered)) - 1]
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    evidence = {
        "algorithm": "O(n log n) ordering + O(total environment bytes) hashing",
        "p50_seconds": round(p50, 6),
        "p95_seconds": round(p95, 6),
        "samples_seconds": [round(item, 6) for item in durations],
    }
    attach_text("admission performance", json.dumps(evidence, sort_keys=True))
    assert_equal(len(durations), 12, "performance sample count")
    assert_true(0 <= p50 <= p95, "performance percentile ordering")


@scenario("A-020", "Ignore repository and user uv configuration")
def verify_uv_config_isolation(repository: LocalExecutionFixture) -> None:
    bypass = repository.root / "uv-config-bypass"
    home = repository.root / "isolated-home"
    home.mkdir()
    (repository.root / "uv.toml").write_text(
        'python-downloads-json-url = "https://poison.invalid/python.json"\n',
        encoding="utf-8",
    )
    (home / "uv.toml").write_text(
        'python-downloads-json-url = "https://poison.invalid/user.json"\n',
        encoding="utf-8",
    )
    completed = run_flare(
        repository,
        "bootstrap",
        extra_environment={"UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never"},
    )
    assert_equal(completed.returncode, 0, "uv config isolation bootstrap")
    assert_false(bypass.exists(), "uv configuration discovery")
    assert_equal(_inspect(repository), EnvironmentState.ADMITTED, "isolated uv state")


@scenario("A-021", "Hold a shared Stage-0 lock across launch")
def verify_launch_reconstruction_lock(repository: LocalExecutionFixture) -> None:
    assert_equal(run_flare(repository, "bootstrap").returncode, 0, "initial bootstrap")
    state = repository.root / repository.profile.project_state
    (state / "stage0-python.sha256").write_text("0" * 64 + "\n", encoding="ascii")
    started = repository.root / "uv-install-started"
    release = repository.root / "uv-install-release"
    (repository.root / "enable-install-wait").touch()
    environment = flare_environment(repository)
    processes: list[subprocess.Popen[str]] = []
    try:
        bootstrap = subprocess.Popen(
            (str(repository.root / "flare"), "bootstrap"),
            cwd=repository.root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append(bootstrap)
        _wait_for_path(started)
        doctor = subprocess.Popen(
            (str(repository.root / "flare"), "doctor"),
            cwd=repository.root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append(doctor)
        time.sleep(0.2)
        assert_true(doctor.poll() is None, "doctor waits for Stage-0 reconstruction")
        release.write_text("release\n", encoding="ascii")
        bootstrap_output = bootstrap.communicate(timeout=30)
        doctor_output = doctor.communicate(timeout=30)
        assert_equal(bootstrap.returncode, 0, "reconstruction bootstrap exit")
        assert_equal(doctor.returncode, 0, "post-reconstruction doctor exit")
        assert_contains("bootstrap=PASS", bootstrap_output[0], "bootstrap output")
        assert_contains("doctor=PASS", doctor_output[0], "doctor output")
    finally:
        release.touch(exist_ok=True)
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


@scenario("A-022", "Inspect candidate bytes before project-Python execution")
def verify_candidate_observation_is_filesystem_only(
    repository: LocalExecutionFixture,
) -> None:
    probe = repository.root / "stage1-environment-probe.json"
    bootstrap_fixture(repository)
    script = repository.root / ".venv/bin/fixture-tool"
    script_bytes = script.read_bytes()
    first_line, body = script_bytes.split(b"\n", maxsplit=1)
    assert_contains(
        os.fsencode(repository.root / ".venv").decode(),
        first_line.decode(),
        "relocated script",
    )
    assert_false(b"candidate-" in first_line, "candidate launcher path")
    assert_contains("body-only:", body.decode(), "unchanged script body")
    assert_contains("candidate-", body.decode(), "body candidate canary")
    assert_false(probe.exists(), "candidate startup before admission")
    script_environment = flare_environment(repository)
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
        script_environment.pop(name)
    executed = subprocess.run(
        (str(script),),
        cwd=repository.root,
        env=script_environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    assert_equal(executed.returncode, 0, "relocated console script exit")
    assert_contains("body-only:", executed.stdout, "relocated console script output")
    assert_contains("candidate-", executed.stdout, "unchanged body value at runtime")
    assert_true(probe.exists(), "admitted console script startup")
    probe.unlink()
    doctor = run_flare(repository, "doctor")
    assert_equal(doctor.returncode, 0, "admitted candidate doctor")
    assert_true(probe.exists(), "admitted Stage-1 startup")


@scenario("A-023", "Reject oversized admission before filesystem publication")
def verify_admission_publication_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    with monkeypatch.context() as scoped:
        scoped.setattr(admission_module, "MAX_RECORD_BYTES", 8)

        def publish() -> None:
            publish_admission(state, {"oversized": "record"})

        error = assert_raises(AdmissionError, publish, "oversized admission")
    assert_contains("byte bound", str(error), "bounded publication error")
    assert_false((state / ADMISSION_NAME).exists(), "admission record absent")
    assert_false((state / ADMISSION_DIGEST_NAME).exists(), "admission digest absent")
    assert_equal(tuple(state.iterdir()), (), "no admission temporaries")
