from __future__ import annotations

import fcntl
import os
import shlex
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE_ROOT))

from tools.local_execution.admission import AdmissionError, inspect_admission
from tools.local_execution.bootstrap import bootstrap_command
from tools.local_execution.model import Capability
from tools.local_execution.profile import ProfileError, load_profile

PROFILE_PATH = SOURCE_ROOT / "tools/local_execution/host_profile.toml"
_HOOK_COMMANDS = {
    "pre-commit": ("check-fast",),
    "commit-msg": ("commit-msg", '"${1:?commit message path is required}"'),
    "pre-push": ("check",),
}
_MINIMAL_GIT_ENVIRONMENT = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "HOME": "/nonexistent",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/usr/bin:/bin",
}
_PROJECT_ENVIRONMENT_BASE = {
    **_MINIMAL_GIT_ENVIRONMENT,
    "PIP_CONFIG_FILE": "/dev/null",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "TMPDIR": "/tmp",
    "UV_NO_CONFIG": "1",
}
_MAX_GIT_CONTROL_BYTES = 4096
_MAX_GIT_CONFIG_BYTES = 1024 * 1024


def _lock_descriptor(path: Path) -> int:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        os.close(descriptor)
        raise AdmissionError("bootstrap lock metadata is invalid")
    return descriptor


def _shell_environment(environment: dict[str, str]) -> str:
    return " ".join(
        f"{name}={shlex.quote(value)}" for name, value in environment.items()
    )


def _hook_payload(arguments: tuple[str, ...]) -> bytes:
    suffix = " ".join(arguments)
    git_environment = _shell_environment(_MINIMAL_GIT_ENVIRONMENT)
    project_environment = _shell_environment(_PROJECT_ENVIRONMENT_BASE)
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        f"ROOT=$(/usr/bin/env -i {git_environment} "
        "/usr/bin/git rev-parse --show-toplevel)\n"
        "exec /usr/bin/env -i "
        'FLARE_HOST_UV="${FLARE_HOST_UV:?FLARE_HOST_UV is required}" '
        f'{project_environment} "$ROOT/flare" {suffix}\n'
    ).encode()


def _run_git_unchecked(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("/usr/bin/git", "-C", str(SOURCE_ROOT), *arguments),
        cwd=SOURCE_ROOT,
        env=dict(_MINIMAL_GIT_ENVIRONMENT),
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )


def _read_owned_regular_file(path: Path, label: str, limit: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as error:
        raise AdmissionError(f"{label} is unavailable") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or metadata.st_size > limit
            or stat.S_IMODE(metadata.st_mode) & 0o002
        ):
            raise AdmissionError(f"{label} metadata is unsafe")
        raw = os.read(descriptor, limit + 1)
        current = path.lstat()
        if len(raw) != metadata.st_size or (current.st_dev, current.st_ino) != (
            metadata.st_dev,
            metadata.st_ino,
        ):
            raise AdmissionError(f"{label} changed while reading")
        return raw
    finally:
        os.close(descriptor)


def _unchecked_absolute_git_paths(*arguments: str) -> tuple[Path, ...]:
    completed = _run_git_unchecked("rev-parse", "--path-format=absolute", *arguments)
    lines = completed.stdout.splitlines()
    if (
        completed.returncode != 0
        or completed.stderr
        or len(lines) != len(arguments)
        or any(not line or line.strip() != line for line in lines)
    ):
        raise AdmissionError("unable to verify this checkout's Git paths")
    paths = tuple(Path(line) for line in lines)
    if any(not path.is_absolute() for path in paths):
        raise AdmissionError("Git returned a non-absolute control path")
    return paths


def _linked_git_directories(control: Path) -> tuple[Path, Path]:
    raw = _read_owned_regular_file(
        control, "linked-worktree Git file", _MAX_GIT_CONTROL_BYTES
    )
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeError as error:
        raise AdmissionError("linked-worktree Git file is not UTF-8") from error
    if (
        not text.startswith("gitdir: ")
        or text.count("\n") != 1
        or not text.endswith("\n")
    ):
        raise AdmissionError("linked-worktree Git file framing is invalid")
    target = Path(text.removeprefix("gitdir: ").removesuffix("\n"))
    try:
        target_resolved = target.resolve(strict=True)
        target_metadata = target.lstat()
    except (OSError, RuntimeError) as error:
        raise AdmissionError("linked-worktree Git directory is unavailable") from error
    if (
        not target.is_absolute()
        or target != target_resolved
        or not stat.S_ISDIR(target_metadata.st_mode)
        or target_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(target_metadata.st_mode) & 0o002
    ):
        raise AdmissionError("linked-worktree Git directory metadata is unsafe")
    return target, _linked_git_common_directory(control, target)


def _linked_git_common_directory(control: Path, target: Path) -> Path:
    backlink = _read_owned_regular_file(
        target / "gitdir", "linked-worktree backlink", _MAX_GIT_CONTROL_BYTES
    )
    expected_backlink = f"{control}\n".encode()
    if backlink != expected_backlink:
        raise AdmissionError("linked-worktree backlink is invalid")
    commondir = _read_owned_regular_file(
        target / "commondir", "common-dir link", _MAX_GIT_CONTROL_BYTES
    )
    try:
        relative = Path(commondir.decode("utf-8", "strict").removesuffix("\n"))
        common = (target / relative).resolve(strict=True)
        metadata = common.lstat()
    except (UnicodeError, OSError, RuntimeError) as error:
        raise AdmissionError(
            "linked-worktree common directory is unavailable"
        ) from error
    if (
        not commondir.endswith(b"\n")
        or commondir.count(b"\n") != 1
        or relative.is_absolute()
        or target.parent.name != "worktrees"
        or common != target.parent.parent
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o002
    ):
        raise AdmissionError("linked-worktree common directory metadata is unsafe")
    return common


def _run_git_config_file(
    config: Path, *arguments: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (
            "/usr/bin/git",
            "config",
            "--file",
            str(config),
            "--no-includes",
            *arguments,
        ),
        cwd=SOURCE_ROOT,
        env=dict(_MINIMAL_GIT_ENVIRONMENT),
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )


def _require_include_free_common_config(common: Path) -> Path:
    config = common / "config"
    before = _read_owned_regular_file(
        config, "Git common configuration", _MAX_GIT_CONFIG_BYTES
    )
    completed = _run_git_config_file(
        config,
        "--name-only",
        "--get-regexp",
        r"^(include\.path|includeif\..*\.path)$",
    )
    after = _read_owned_regular_file(
        config, "Git common configuration", _MAX_GIT_CONFIG_BYTES
    )
    if after != before:
        raise AdmissionError("Git common configuration changed during inspection")
    if completed.returncode == 1 and not completed.stdout and not completed.stderr:
        return config
    if completed.returncode == 0 and completed.stdout and not completed.stderr:
        raise AdmissionError("Git common configuration includes are unsupported")
    raise AdmissionError("unable to inspect Git common configuration includes")


def _require_safe_source_git_control() -> None:
    control = SOURCE_ROOT / ".git"
    try:
        metadata = control.lstat()
    except OSError as error:
        raise AdmissionError("checkout Git control path is unavailable") from error
    if stat.S_ISDIR(metadata.st_mode):
        if metadata.st_uid != os.geteuid():
            raise AdmissionError("checkout Git directory has a foreign owner")
        git_directory = common = control
    elif stat.S_ISREG(metadata.st_mode):
        git_directory, common = _linked_git_directories(control)
    else:
        raise AdmissionError("checkout Git control path has an unsafe file type")
    _require_include_free_common_config(common)
    observed = _unchecked_absolute_git_paths("--absolute-git-dir", "--git-common-dir")
    if observed != (git_directory, common):
        raise AdmissionError("checkout Git control paths do not match repository truth")


def _run_git(*arguments: str) -> subprocess.CompletedProcess[str]:
    _require_safe_source_git_control()
    return _run_git_unchecked(*arguments)


def _git_path(*arguments: str) -> Path:
    completed = _run_git("rev-parse", *arguments)
    lines = completed.stdout.splitlines()
    if (
        completed.returncode != 0
        or len(lines) != 1
        or not lines[0]
        or lines[0].strip() != lines[0]
    ):
        raise AdmissionError("unable to resolve this checkout's Git path")
    value = Path(lines[0])
    return value if value.is_absolute() else SOURCE_ROOT / value


def _require_shared_local_config() -> None:
    completed = _run_git("config", "--bool", "--get", "extensions.worktreeConfig")
    if completed.returncode == 1 and not completed.stdout and not completed.stderr:
        return
    if (
        completed.returncode == 0
        and completed.stdout == "false\n"
        and not completed.stderr
    ):
        return
    raise AdmissionError("per-worktree Git configuration is unsupported")


def _require_exact_effective_pin(config: Path, hooks: Path) -> None:
    completed = _run_git(
        "config",
        "--includes",
        "--null",
        "--show-origin",
        "--show-scope",
        "--get-all",
        "core.hooksPath",
    )
    fields = completed.stdout.split("\0")
    if (
        completed.returncode != 0
        or completed.stderr
        or len(fields) != 4
        or fields[0] != "local"
        or not fields[1].startswith("file:")
        or fields[2] != str(hooks)
        or fields[3]
    ):
        raise AdmissionError("effective Git hooks pin is not exact")
    origin = Path(fields[1].removeprefix("file:"))
    origin = origin if origin.is_absolute() else SOURCE_ROOT / origin
    try:
        resolved_origin = origin.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise AdmissionError("effective Git hooks pin origin is unavailable") from error
    if resolved_origin != config:
        raise AdmissionError("effective Git hooks pin origin is not local")


def _pin_hooks_path(config: Path, hooks: Path) -> None:
    completed = _run_git(
        "config", "--local", "--replace-all", "core.hooksPath", str(hooks)
    )
    if completed.returncode != 0 or completed.stdout or completed.stderr:
        raise AdmissionError("unable to pin repository-common Git hooks path")
    _require_exact_effective_pin(config, hooks)
    effective = _git_path("--git-path", "hooks")
    if not effective.is_absolute() or effective != hooks:
        raise AdmissionError("effective Git hooks path does not match the local pin")
    descriptor = os.open(config, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) & 0o002
        ):
            raise AdmissionError("pinned Git configuration metadata is unsafe")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    descriptor = os.open(hooks.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _hooks_directory() -> tuple[Path, Path]:
    common = _git_path("--git-common-dir")
    try:
        common_resolved = common.resolve(strict=True)
        common_metadata = common_resolved.lstat()
    except (OSError, RuntimeError) as error:
        raise AdmissionError("Git common directory is unavailable") from error
    if (
        common_resolved.is_symlink()
        or not stat.S_ISDIR(common_metadata.st_mode)
        or common_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(common_metadata.st_mode) & 0o002
    ):
        raise AdmissionError("Git common directory metadata is unsafe")
    hooks = common_resolved / "hooks"
    config = _require_include_free_common_config(common_resolved)
    _require_shared_local_config()
    try:
        metadata = hooks.lstat()
    except FileNotFoundError:
        try:
            hooks.mkdir(mode=0o755)
            metadata = hooks.lstat()
        except OSError as error:
            raise AdmissionError("Git hooks directory is unavailable") from error
    if (
        hooks.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
    ):
        raise AdmissionError("Git hooks directory metadata is unsafe")
    return hooks, config


def _validate_hook_target(path: Path) -> None:
    if path.is_symlink():
        raise AdmissionError(f"refusing to replace symlink hook: {path.name}")
    if path.exists():
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise AdmissionError(f"existing hook metadata is unsafe: {path.name}")


def _install_hook(path: Path, payload: bytes) -> None:
    _validate_hook_target(path)
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_path)
    try:
        os.fchmod(descriptor, 0o755)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _install_hooks() -> int:
    hooks, config = _hooks_directory()
    targets = tuple(hooks / name for name in _HOOK_COMMANDS)
    for target in targets:
        _validate_hook_target(target)
    hooks.chmod(stat.S_IMODE(hooks.stat().st_mode) & ~0o022)
    for name, arguments in _HOOK_COMMANDS.items():
        _install_hook(hooks / name, _hook_payload(arguments))
    descriptor = os.open(hooks, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _pin_hooks_path(config, hooks)
    print("hooks=INSTALLED admission=PASS")
    return 0


def _option(arguments: list[str], name: str) -> tuple[str | None, list[str]]:
    remaining: list[str] = []
    found: str | None = None
    index = 0
    while index < len(arguments):
        if arguments[index] == name:
            if found is not None or index + 1 >= len(arguments):
                raise ValueError(f"option {name} requires one value")
            found = arguments[index + 1]
            index += 2
        else:
            remaining.append(arguments[index])
            index += 1
    return found, remaining


def _required_option(arguments: list[str], name: str) -> tuple[str, list[str]]:
    value, remaining = _option(arguments, name)
    if value is None:
        raise ValueError(f"option {name} is required")
    return value, remaining


def _project_environment() -> dict[str, str]:
    environment = dict(_PROJECT_ENVIRONMENT_BASE)
    for name in ("SSL_CERT_DIR", "SSL_CERT_FILE"):
        if (value := os.environ.get(name)) is not None:
            environment[name] = value
    return environment


def _project_argv(command: str, arguments: list[str], uv: Path) -> tuple[str, ...]:
    python = str(SOURCE_ROOT / ".venv/bin/python")
    if command == "commit-msg":
        if len(arguments) != 1:
            raise ValueError("commit-msg requires exactly one message path")
        return (
            python,
            "-m",
            "gitlint.cli",
            "--config",
            ".gitlint",
            "--msg-filename",
            arguments[0],
        )
    try:
        capability = Capability(command)
    except ValueError as error:
        raise ValueError(f"unknown admitted command: {command}") from error
    if capability is Capability.BOOTSTRAP or arguments:
        raise ValueError(f"invalid arguments for admitted command: {command}")
    return (
        python,
        "-m",
        "tools.local_execution",
        command,
        "--uv",
        str(uv),
    )


def _launch(
    command: str,
    arguments: list[str],
    uv: Path,
    managed_python: Path,
) -> int:
    profile = load_profile(PROFILE_PATH)
    state = profile.path(SOURCE_ROOT, profile.project_state)
    lock_path = state / "bootstrap.lock"
    project_python = (
        profile.path(SOURCE_ROOT, profile.project_environment) / "bin/python"
    )
    try:
        with os.fdopen(_lock_descriptor(lock_path), "rb") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
            before = project_python.lstat()
            inspection = inspect_admission(SOURCE_ROOT, profile, uv, managed_python)
            after = project_python.lstat()
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise RuntimeError("project Python changed during admission")
            if not inspection.admitted:
                print(
                    f"project_environment={inspection.state.value} REQUIRED",
                    file=sys.stderr,
                )
                print(f"admission=FAIL detail={inspection.detail}", file=sys.stderr)
                return 1
            if command == "install-hooks":
                if arguments:
                    raise ValueError("install-hooks accepts no arguments")
                return _install_hooks()
            argv = _project_argv(command, arguments, uv)
            os.set_inheritable(lock.fileno(), True)
            os.execve(str(project_python), argv, _project_environment())
    except (AdmissionError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(
            "project_environment=UNADMITTED REQUIRED\n"
            f"admission=FAIL detail={type(error).__name__}",
            file=sys.stderr,
        )
        return 1


def main(arguments: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if arguments is None else arguments)
    if not args:
        print("admission command is required", file=sys.stderr)
        return 2
    action = args.pop(0)
    try:
        uv_value, args = _required_option(args, "--uv")
        managed_value, args = _required_option(args, "--managed-python")
        uv = Path(uv_value)
        managed_python = Path(managed_value)
        profile = load_profile(PROFILE_PATH)
        if action == "bootstrap":
            if args:
                raise ValueError("bootstrap accepts no additional arguments")
            return bootstrap_command(SOURCE_ROOT, profile, uv, managed_python)
        if action != "launch" or not args:
            raise ValueError("admission action must be bootstrap or launch")
        command = args.pop(0)
        if args[:1] == ["--"]:
            args.pop(0)
        return _launch(command, args, uv, managed_python)
    except (AdmissionError, ProfileError, ValueError) as error:
        print(f"admission arguments invalid: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
