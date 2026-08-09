import fcntl
import os
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

from tools.local_execution.environment import (
    MANIFEST_NAME,
    EnvironmentError,
    EnvironmentManifest,
    environment_marker_matches,
    observe_environment,
    validate_environment,
)
from tools.local_execution.model import BootstrapResult, CheckStatus
from tools.local_execution.profile import HostProfile

type FaultHook = Callable[[str], None]


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
    except ValueError:
        return False
    return True


def _require_safe_paths(root: Path, profile: HostProfile) -> None:
    state = profile.path(root, profile.project_state)
    targets = (
        profile.path(root, profile.project_environment),
        state,
        state / "bootstrap.lock",
        state / "candidates",
        state / "rejected",
        profile.path(root, profile.python_install_dir),
        profile.path(root, profile.uv_cache),
    )
    if any(path.resolve(strict=False) == root.resolve(strict=True) for path in targets):
        raise EnvironmentError("bootstrap target resolves to the repository root")
    if any(not _inside(root, path) for path in targets):
        raise EnvironmentError(
            "bootstrap target escapes its declared project-local root"
        )


def _python_in(environment: Path) -> Path:
    return environment / "bin/python"


def _current_manifest(
    root: Path,
    profile: HostProfile,
    environment: Path,
    uv: Path,
) -> EnvironmentManifest | None:
    python = _python_in(environment)
    if not python.is_file():
        return None
    try:
        manifest = observe_environment(root, profile, python, uv)
    except EnvironmentError, OSError, TimeoutError:
        return None
    if not environment_marker_matches(environment, manifest) or validate_environment(
        root, profile, manifest
    ):
        return None
    return manifest


def _sync_environment(
    root: Path,
    profile: HostProfile,
    uv: Path,
    managed_python: Path,
    candidate: Path,
) -> subprocess.CompletedProcess[str]:
    inherited_names = (
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TMPDIR",
        *profile.external_package_source_environment,
    )
    environment = {
        name: value
        for name in inherited_names
        if (value := os.environ.get(name)) is not None
    }
    environment.update(
        {
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
            "sync",
            "--frozen",
            "--python",
            str(managed_python),
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=600,
    )


def bootstrap_environment(
    root: Path,
    profile: HostProfile,
    uv: Path,
    managed_python: Path,
    fault_hook: FaultHook | None = None,
) -> BootstrapResult:
    _require_safe_paths(root, profile)
    managed_root = profile.path(root, profile.python_install_dir)
    if not _inside(managed_root, managed_python) or not managed_python.is_file():
        raise EnvironmentError(
            "managed Python must be an executable inside the declared project-local install root"
        )
    state = profile.path(root, profile.project_state)
    candidates = state / "candidates"
    rejected = state / "rejected"
    state.mkdir(parents=True, exist_ok=True)
    lock_path = state / "bootstrap.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        environment = profile.path(root, profile.project_environment)
        current = _current_manifest(root, profile, environment, uv)
        if current is not None:
            return BootstrapResult(
                CheckStatus.PASS,
                "REUSED",
                "existing project environment matches repository truth",
                current.sha256,
            )
        candidates.mkdir(parents=True, exist_ok=True)
        candidate = Path(tempfile.mkdtemp(prefix="candidate-", dir=str(candidates)))
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
        if fault_hook is not None:
            fault_hook("after-sync")
        try:
            manifest = observe_environment(root, profile, _python_in(candidate), uv)
            errors = validate_environment(root, profile, manifest)
        except (EnvironmentError, OSError, TimeoutError) as error:
            return BootstrapResult(
                CheckStatus.FAIL, "VALIDATION_FAILED", str(error), None
            )
        if errors:
            return BootstrapResult(
                CheckStatus.FAIL,
                "VALIDATION_FAILED",
                "; ".join(errors),
                None,
            )
        (candidate / MANIFEST_NAME).write_bytes(manifest.encoded())
        if fault_hook is not None:
            fault_hook("before-activation")
        if environment.exists() or environment.is_symlink():
            rejected.mkdir(parents=True, exist_ok=True)
            environment.rename(rejected / f"environment-{uuid.uuid4().hex}")
        candidate.rename(environment)
        return BootstrapResult(
            CheckStatus.PASS,
            "CREATED",
            "validated candidate activated atomically",
            manifest.sha256,
        )


def bootstrap_command(
    root: Path,
    profile: HostProfile,
    uv: Path,
    managed_python: Path,
) -> int:
    try:
        result = bootstrap_environment(root, profile, uv, managed_python)
    except (EnvironmentError, OSError, subprocess.SubprocessError) as error:
        result = BootstrapResult(CheckStatus.FAIL, "BOOTSTRAP_FAILED", str(error), None)
    print(f"bootstrap={result.status.value}")
    print(f"action={result.action}")
    print(f"detail={result.detail}")
    if result.manifest_sha256 is not None:
        print(f"manifest_sha256={result.manifest_sha256}")
    return 0 if result.passed else 1
