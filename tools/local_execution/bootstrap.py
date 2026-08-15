from __future__ import annotations

import fcntl
import os
import stat
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

from tools.local_execution.admission import (
    AdmissionError,
    EnvironmentState,
    build_admission_record,
    inspect_admission,
    normalize_environment,
    publish_admission,
    validate_environment_tree,
)
from tools.local_execution.environment import (
    MANIFEST_NAME,
    EnvironmentError,
    observe_environment,
    validate_environment,
)
from tools.local_execution.model import BootstrapResult, CheckStatus
from tools.local_execution.profile import HostProfile

type FaultHook = Callable[[str], None]
type DirectoryIdentity = tuple[int, int, int, int]
MAX_RELOCATABLE_SCRIPT_BYTES = 1_000_000
MAX_RELOCATABLE_SCRIPT_TOTAL_BYTES = 16_000_000
MAX_BINARY_DIRECTORY_ENTRIES = 1_024


def _lexically_inside(root: Path, path: Path) -> bool:
    try:
        path.absolute().relative_to(root.absolute())
    except OSError, RuntimeError, ValueError:
        return False
    return True


def _resolved_inside(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
    except ValueError:
        return False
    return True


def _require_safe_paths(root: Path, profile: HostProfile) -> None:
    state = profile.path(root, profile.project_state)
    environment = profile.path(root, profile.project_environment)
    lexical_targets = (
        environment,
        state,
        state / "bootstrap.lock",
        state / "candidates",
        state / "rejected",
        profile.path(root, profile.python_install_dir),
        profile.path(root, profile.uv_cache),
    )
    if any(path.absolute() == root.absolute() for path in lexical_targets):
        raise EnvironmentError("bootstrap target resolves to the repository root")
    if any(not _lexically_inside(root, path) for path in lexical_targets):
        raise EnvironmentError("bootstrap target escapes its project-local root")

    # The environment directory entry may itself be hostile. It is quarantined
    # without following it. Every bootstrap-owned supporting path must resolve
    # inside the repository before any mutation is attempted.
    protected = tuple(path for path in lexical_targets if path != environment)
    if any(not _resolved_inside(root, path) for path in protected):
        raise EnvironmentError("bootstrap state path escapes its project-local root")


def _require_directory(path: Path, mode: int) -> None:
    path.mkdir(parents=True, mode=mode, exist_ok=True)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise EnvironmentError(f"unsafe bootstrap directory: {path.name}")
    path.chmod(mode)


def _prepare_state(root: Path, profile: HostProfile) -> tuple[Path, Path, Path]:
    state = profile.path(root, profile.project_state)
    _require_directory(state, 0o700)
    candidates = state / "candidates"
    rejected = state / "rejected"
    _require_directory(candidates, 0o700)
    _require_directory(rejected, 0o700)
    return state, candidates, rejected


def _directory_identity(path: Path, label: str) -> DirectoryIdentity:
    metadata = path.lstat()
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or mode & 0o022
    ):
        raise EnvironmentError(f"{label} directory identity is unsafe")
    return metadata.st_dev, metadata.st_ino, metadata.st_uid, mode


def _require_directory_identity(
    path: Path, expected: DirectoryIdentity, label: str
) -> None:
    if _directory_identity(path, label) != expected:
        raise EnvironmentError(f"{label} directory identity changed")


def _bootstrap_lock_descriptor(state: Path) -> int:
    directory = os.open(
        state,
        os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    try:
        descriptor = os.open(
            "bootstrap.lock",
            os.O_RDWR | os.O_APPEND | os.O_CLOEXEC | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
    finally:
        os.close(directory)
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
    ):
        os.close(descriptor)
        raise EnvironmentError("bootstrap lock metadata is unsafe")
    os.fchmod(descriptor, 0o600)
    return descriptor


def _require_managed_python(root: Path, profile: HostProfile, python: Path) -> None:
    managed_root = profile.path(root, profile.python_install_dir)
    try:
        resolved_root = managed_root.resolve(strict=True)
        resolved = python.resolve(strict=True)
        metadata = resolved.stat()
        resolved.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError) as error:
        raise EnvironmentError(
            "managed Python must resolve inside the project-local install root"
        ) from error
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or not os.access(resolved, os.X_OK)
        or metadata.st_uid not in {0, os.geteuid()}
        or mode & 0o022
    ):
        raise EnvironmentError("managed Python identity metadata is unsafe")


def _sync_environment(
    root: Path,
    profile: HostProfile,
    uv: Path,
    managed_python: Path,
    candidate: Path,
) -> subprocess.CompletedProcess[str]:
    inherited_names = (
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        *profile.external_package_source_environment,
    )
    environment = {
        name: value
        for name in inherited_names
        if (value := os.environ.get(name)) is not None
    }
    environment.update(
        {
            "HOME": "/nonexistent",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": "/tmp",
            "UV_CACHE_DIR": str(profile.path(root, profile.uv_cache)),
            "UV_PROJECT_ENVIRONMENT": str(candidate),
            "UV_PYTHON_INSTALL_DIR": str(
                profile.path(root, profile.python_install_dir)
            ),
        }
    )
    return subprocess.run(
        [
            str(uv),
            "--no-config",
            "sync",
            "--frozen",
            "--python",
            str(managed_python),
            "--link-mode",
            "copy",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=600,
    )


def _invalidate_admission(state: Path) -> None:
    # The digest is the publication point. Removing it first makes every crash
    # after this line fail closed.
    for name in ("environment-admission-v1.sha256", "environment-admission-v1.json"):
        path = state / name
        if path.exists() or path.is_symlink():
            path.unlink()


def _quarantine(environment: Path, rejected: Path) -> None:
    if environment.exists() or environment.is_symlink():
        environment.rename(rejected / f"environment-{uuid.uuid4().hex}")


def _validated_candidate(
    root: Path,
    profile: HostProfile,
    uv: Path,
    candidate: Path,
) -> tuple[bytes, str]:
    manifest = observe_environment(root, profile, candidate, uv)
    errors = validate_environment(root, profile, manifest)
    if errors:
        raise EnvironmentError("; ".join(errors))
    return manifest.encoded(), manifest.sha256


def _script_payload(descriptor: int) -> bytes:
    first = os.read(descriptor, 2)
    if first != b"#!":
        return b""
    chunks = [first]
    size = 2
    while size <= MAX_RELOCATABLE_SCRIPT_BYTES:
        chunk = os.read(
            descriptor,
            min(65_536, MAX_RELOCATABLE_SCRIPT_BYTES + 1 - size),
        )
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        size += len(chunk)
    if size > MAX_RELOCATABLE_SCRIPT_BYTES:
        raise EnvironmentError("candidate script exceeds the relocation byte bound")
    raise AssertionError("unreachable script payload state")


def _relocated_script(
    payload: bytes,
    candidate: bytes,
    environment: bytes,
) -> bytes | None:
    lines = payload.splitlines(keepends=True)
    if not lines:
        return None
    direct_prefix = b"#!" + candidate + b"/bin/python"
    if lines[0].startswith(direct_prefix):
        suffix = lines[0][len(direct_prefix) :].rstrip(b"\r\n")
        if suffix and not (
            suffix.replace(b".", b"").isdigit() or suffix.startswith(b" -")
        ):
            raise EnvironmentError("candidate script shebang is ambiguous")
        lines[0] = lines[0].replace(candidate, environment, 1)
        return b"".join(lines)
    shell_prefix = b"'''exec' '" + candidate + b'/bin/python\' "$0" "$@"'
    if (
        lines[0].rstrip(b"\r\n") == b"#!/bin/sh"
        and len(lines) >= 3
        and lines[1].rstrip(b"\r\n") == shell_prefix
        and lines[2].rstrip(b"\r\n") == b"' '''"
    ):
        lines[1] = lines[1].replace(candidate, environment, 1)
        return b"".join(lines)
    if candidate in lines[0] or (len(lines) > 1 and candidate in lines[1]):
        raise EnvironmentError("candidate script launcher is ambiguous")
    return None


def _relocate_candidate_scripts(candidate: Path, environment: Path) -> None:
    binary_directory = candidate / "bin"
    candidate_bytes = os.fsencode(candidate)
    environment_bytes = os.fsencode(environment)
    directory = os.open(
        binary_directory,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        directory_metadata = os.fstat(directory)
        if (
            not stat.S_ISDIR(directory_metadata.st_mode)
            or directory_metadata.st_uid != os.geteuid()
            or directory_metadata.st_dev != candidate.stat().st_dev
        ):
            raise EnvironmentError("candidate script directory is unsafe")
        entry_count = 0
        total_script_bytes = 0
        with os.scandir(directory) as entries:
            for entry in entries:
                entry_count += 1
                if entry_count > MAX_BINARY_DIRECTORY_ENTRIES:
                    raise EnvironmentError("candidate bin entry bound exceeded")
                metadata = entry.stat(follow_symlinks=False)
                if not stat.S_ISREG(metadata.st_mode):
                    continue
                descriptor = os.open(
                    entry.name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory,
                )
                try:
                    payload = _script_payload(descriptor)
                    opened = os.fstat(descriptor)
                finally:
                    os.close(descriptor)
                expected = (
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_mode,
                    metadata.st_size,
                    metadata.st_uid,
                )
                actual = (
                    opened.st_dev,
                    opened.st_ino,
                    opened.st_mode,
                    opened.st_size,
                    opened.st_uid,
                )
                if actual != expected:
                    raise EnvironmentError("candidate script identity changed")
                total_script_bytes += len(payload)
                if total_script_bytes > MAX_RELOCATABLE_SCRIPT_TOTAL_BYTES:
                    raise EnvironmentError("candidate script total byte bound exceeded")
                relocated = _relocated_script(
                    payload,
                    candidate_bytes,
                    environment_bytes,
                )
                if relocated is None:
                    continue
                temporary_descriptor, temporary_name = tempfile.mkstemp(
                    prefix=f".{entry.name}.", dir=binary_directory
                )
                temporary = Path(temporary_name)
                try:
                    os.fchmod(temporary_descriptor, stat.S_IMODE(metadata.st_mode))
                    with os.fdopen(temporary_descriptor, "wb") as stream:
                        stream.write(relocated)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, binary_directory / entry.name)
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
        os.fsync(directory)
    finally:
        os.close(directory)


def _fault(fault_hook: FaultHook | None, phase: str) -> None:
    if fault_hook is not None:
        fault_hook(phase)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_marker(candidate: Path, identity: DirectoryIdentity, payload: bytes) -> None:
    directory = os.open(
        candidate,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    metadata = os.fstat(directory)
    observed = (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_uid,
        stat.S_IMODE(metadata.st_mode),
    )
    if observed != identity:
        os.close(directory)
        raise EnvironmentError("candidate directory identity changed")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        descriptor = os.open(MANIFEST_NAME, flags, 0o600, dir_fd=directory)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory)
    finally:
        os.close(directory)


def bootstrap_environment(
    root: Path,
    profile: HostProfile,
    uv: Path,
    managed_python: Path,
    fault_hook: FaultHook | None = None,
) -> BootstrapResult:
    _require_safe_paths(root, profile)
    _require_managed_python(root, profile, managed_python)
    state, candidates, rejected = _prepare_state(root, profile)
    with os.fdopen(_bootstrap_lock_descriptor(state), "a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        environment = profile.path(root, profile.project_environment)
        inspection = inspect_admission(root, profile, uv, managed_python)
        if inspection.state is EnvironmentState.ADMITTED:
            return BootstrapResult(
                CheckStatus.PASS,
                "REUSED",
                "existing environment has an exact current admission seal",
                inspection.marker_sha256,
            )

        _invalidate_admission(state)
        _quarantine(environment, rejected)
        candidate = Path(tempfile.mkdtemp(prefix="candidate-", dir=str(candidates)))
        candidate_identity = _directory_identity(candidate, "candidate")
        synced = _sync_environment(root, profile, uv, managed_python, candidate)
        if synced.returncode != 0:
            return BootstrapResult(
                CheckStatus.FAIL,
                "SYNC_FAILED",
                "locked environment reconstruction failed "
                f"(uv exit {synced.returncode}); inspect configured package-source "
                "variable names with ./flare doctor",
                None,
            )
        _fault(fault_hook, "after-sync")
        try:
            _require_directory_identity(candidate, candidate_identity, "candidate")
            _relocate_candidate_scripts(candidate, environment)
            marker, marker_sha256 = _validated_candidate(root, profile, uv, candidate)
            _write_marker(candidate, candidate_identity, marker)
            normalize_environment(candidate)
            _require_directory_identity(candidate, candidate_identity, "candidate")
            validate_environment_tree(candidate, managed_python)
            _fsync_directory(candidate)
        except (AdmissionError, EnvironmentError, OSError, TimeoutError) as error:
            return BootstrapResult(
                CheckStatus.FAIL, "VALIDATION_FAILED", str(error), None
            )
        _fault(fault_hook, "after-candidate-validation")
        _fault(fault_hook, "before-activation")
        _require_directory_identity(candidate, candidate_identity, "candidate")
        candidate.rename(environment)
        _fsync_directory(root)
        _fsync_directory(candidates)
        _fault(fault_hook, "after-environment-activation")
        try:
            record = build_admission_record(
                root, profile, environment, uv, managed_python
            )
            publish_admission(state, record, fault_hook)
            final = inspect_admission(root, profile, uv, managed_python)
        except (AdmissionError, EnvironmentError, OSError, TimeoutError) as error:
            return BootstrapResult(
                CheckStatus.FAIL, "ADMISSION_FAILED", str(error), None
            )
        if not final.admitted:
            return BootstrapResult(
                CheckStatus.FAIL,
                "ADMISSION_FAILED",
                f"published environment is {final.state.value}: {final.detail}",
                None,
            )
        return BootstrapResult(
            CheckStatus.PASS,
            "CREATED",
            "validated candidate activated and admitted atomically",
            marker_sha256,
        )


def bootstrap_command(
    root: Path,
    profile: HostProfile,
    uv: Path,
    managed_python: Path,
) -> int:
    try:
        result = bootstrap_environment(root, profile, uv, managed_python)
    except (
        AdmissionError,
        EnvironmentError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        result = BootstrapResult(CheckStatus.FAIL, "BOOTSTRAP_FAILED", str(error), None)
    print(f"bootstrap={result.status.value}")
    print(f"action={result.action}")
    print(f"detail={result.detail}")
    if result.manifest_sha256 is not None:
        print(f"manifest_sha256={result.manifest_sha256}")
    return 0 if result.passed else 1
