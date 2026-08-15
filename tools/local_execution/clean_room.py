import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from tools.local_execution.clean_room_retention import (
    CHECKOUT_NAMES,
    SOURCE_MANIFEST_NAME,
    CleanRoomRetentionError,
    compact_successful_run,
    host_state_name,
    require_evidence_bounds,
)
from tools.local_execution.clean_room_source import discover_source_paths
from tools.local_execution.clean_room_source_supervisor import (
    MAX_PROCESS_OUTPUT_BYTES,
    OUTPUT_LIMIT_EXIT,
)
from tools.local_execution.supervisor_client import (
    communicate_supervisor,
    shutdown_supervisor,
)
from tools.project_state.model import JSONValue
from tools.quality.source_manifest import (
    SourceManifest,
    build_git_source_manifest,
    build_source_manifest,
    read_confined_symlink_target,
)

MAX_OBSERVATION_BYTES = 12_000
SUPERVISOR = Path(__file__).with_name("clean_room_source_supervisor.py")


class CleanRoomError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CommandObservation:
    label: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float

    def value(self) -> dict[str, JSONValue]:
        return {
            "duration_seconds": f"{self.duration_seconds:.3f}",
            "exit_code": self.exit_code,
            "label": self.label,
            "stderr": self.stderr,
            "stdout": self.stdout,
        }


@dataclass(frozen=True, slots=True)
class CheckoutProof:
    checkout_identity: DirectoryIdentity
    host_identity: DirectoryIdentity
    name: str
    source_sha256: str
    environment_manifest: bytes
    observations: tuple[CommandObservation, ...]

    def value(self) -> dict[str, JSONValue]:
        return {
            "environment_manifest_json": self.environment_manifest.decode("utf-8"),
            "name": self.name,
            "observations": [item.value() for item in self.observations],
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True, slots=True)
class ProcessExecution:
    duration_seconds: float
    exit_code: int
    stderr: bytes
    stdout: bytes


@dataclass(frozen=True, slots=True)
class DirectoryIdentity:
    device: int
    inode: int
    mode: int
    owner: int


def _bound(raw: bytes) -> str:
    if len(raw) <= MAX_OBSERVATION_BYTES:
        return raw.decode("utf-8", "replace")
    half = (MAX_OBSERVATION_BYTES - 80) // 2
    omitted = len(raw) - (2 * half)
    return (
        raw[:half].decode("utf-8", "replace")
        + f"\n...[TRUNCATED {omitted} BYTES]...\n"
        + raw[-half:].decode("utf-8", "replace")
    )


def _directory_identity(path: Path, label: str) -> DirectoryIdentity:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as error:
        raise CleanRoomError(
            f"{label} directory is unavailable: {type(error).__name__}:{error.errno}"
        ) from error
    identity = DirectoryIdentity(
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IMODE(metadata.st_mode),
        metadata.st_uid,
    )
    if not stat.S_ISDIR(metadata.st_mode):
        raise CleanRoomError(f"{label} is not a directory")
    if identity.owner != os.geteuid() or identity.mode != 0o700:
        raise CleanRoomError(f"{label} ownership or mode rejected: {identity!r}")
    return identity


def _require_directory_identity(
    path: Path, expected: DirectoryIdentity, label: str
) -> None:
    actual = _directory_identity(path, label)
    if actual != expected:
        raise CleanRoomError(
            f"{label} directory identity changed; "
            f"expected={expected!r}; actual={actual!r}"
        )


def _execute(
    argv: tuple[str, ...],
    root: Path,
    environment: dict[str, str],
    timeout: int,
) -> ProcessExecution:
    started = time.monotonic()
    supervised = (
        sys.executable,
        "-I",
        "-B",
        str(SUPERVISOR),
        str(timeout),
        "--",
        *argv,
    )
    process = subprocess.Popen(
        supervised,
        cwd=root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = communicate_supervisor(process, timeout + 15)
    except BaseException as error:
        try:
            stdout, stderr = shutdown_supervisor(process)
        except BaseException as cleanup_error:
            raise CleanRoomError(
                f"supervisor cleanup handshake failed: {cleanup_error}"
            ) from cleanup_error
        if isinstance(error, subprocess.TimeoutExpired):
            raise subprocess.TimeoutExpired(
                supervised,
                timeout + 15,
                output=stdout,
                stderr=stderr,
            ) from error
        raise
    exit_code = process.returncode
    if exit_code == OUTPUT_LIMIT_EXIT:
        raise CleanRoomError(
            f"combined process output exceeded {MAX_PROCESS_OUTPUT_BYTES} bytes"
        )
    return ProcessExecution(
        time.monotonic() - started,
        exit_code,
        stderr,
        stdout,
    )


def _run(
    label: str,
    argv: tuple[str, ...],
    root: Path,
    environment: dict[str, str],
    *,
    expected: frozenset[int] = frozenset({0}),
) -> CommandObservation:
    completed = _execute(argv, root, environment, 1_200)
    observation = CommandObservation(
        label,
        completed.exit_code,
        _bound(completed.stdout),
        _bound(completed.stderr),
        completed.duration_seconds,
    )
    if completed.exit_code not in expected:
        raise CleanRoomError(
            f"{label} returned {completed.exit_code}; "
            f"stdout={observation.stdout!r}; stderr={observation.stderr!r}"
        )
    return observation


def _write_source_manifest(run_root: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(run_root / SOURCE_MANIFEST_NAME, flags, 0o600)
    try:
        view = memoryview(payload)
        written = 0
        while written < len(payload):
            count = os.write(descriptor, view[written:])
            if count < 1:
                raise OSError("short write while creating source manifest")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _materialize(source: Path, target: Path, manifest: SourceManifest) -> None:
    target.mkdir(parents=True, mode=0o700)
    for entry in manifest.document.files:
        source_path = source / entry.path
        target_path = target / entry.path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if entry.kind == "symlink":
            target_path.symlink_to(read_confined_symlink_target(source, source_path))
        else:
            shutil.copy2(source_path, target_path)


def _source_identity(root: Path) -> str:
    return build_source_manifest(root, discover_source_paths(root)).sha256


def _isolated_environment(root: Path, uv: Path) -> dict[str, str]:
    isolated = root.parent / host_state_name(root.name)
    isolated.mkdir(mode=0o700)
    home = isolated / "home"
    xdg_cache = isolated / "xdg-cache"
    xdg_config = isolated / "xdg-config"
    xdg_data = isolated / "xdg-data"
    for path in (home, xdg_cache, xdg_config, xdg_data):
        path.mkdir(mode=0o700)
    return {
        "FLARE_HOST_UV": str(uv),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "XDG_CACHE_HOME": str(xdg_cache),
        "XDG_CONFIG_HOME": str(xdg_config),
        "XDG_DATA_HOME": str(xdg_data),
    }


def _bootstrap_pair(
    root: Path, environment: dict[str, str]
) -> tuple[CommandObservation, CommandObservation]:
    def execute(index: int) -> CommandObservation:
        return _run(
            f"bootstrap-concurrent-{index}",
            ("./flare", "bootstrap"),
            root,
            environment,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(execute, (1, 2))
    combined = first.stdout + second.stdout
    if combined.count("action=CREATED") != 1 or combined.count("action=REUSED") != 1:
        raise CleanRoomError(
            "concurrent bootstrap did not converge as exactly one CREATED "
            "and one REUSED"
        )
    return first, second


def _prove_checkout(
    name: str,
    source: Path,
    target: Path,
    uv: Path,
    manifest: SourceManifest,
    *,
    concurrent: bool,
) -> CheckoutProof:
    _materialize(source, target, manifest)
    checkout_identity = _directory_identity(target, f"{name} checkout")
    environment = _isolated_environment(target, uv)
    host_state = target.parent / host_state_name(name)
    host_identity = _directory_identity(host_state, f"{name} host state")
    initial_identity = _source_identity(target)
    if initial_identity != manifest.sha256:
        raise CleanRoomError(f"{name} source materialization identity mismatch")
    observations: list[CommandObservation] = [
        _run(
            "doctor-before-bootstrap",
            ("./flare", "doctor"),
            target,
            environment,
            expected=frozenset({1}),
        )
    ]
    if concurrent:
        observations.extend(_bootstrap_pair(target, environment))
    else:
        observations.append(
            _run("bootstrap", ("./flare", "bootstrap"), target, environment)
        )
    observations.extend(
        (
            _run("doctor-after-bootstrap", ("./flare", "doctor"), target, environment),
            _run("bootstrap-repeat", ("./flare", "bootstrap"), target, environment),
            _run("check-fast", ("/usr/bin/make", "check-fast"), target, environment),
        )
    )
    manifest_result = _execute(
        ("./flare", "environment-manifest"), target, environment, 60
    )
    if manifest_result.exit_code != 0:
        raise CleanRoomError(
            f"{name} environment manifest failed: {_bound(manifest_result.stderr)}"
        )
    final_identity = _source_identity(target)
    if final_identity != initial_identity:
        raise CleanRoomError(f"{name} bootstrap mutated source truth")
    _require_directory_identity(target, checkout_identity, f"{name} checkout")
    _require_directory_identity(host_state, host_identity, f"{name} host state")
    return CheckoutProof(
        checkout_identity=checkout_identity,
        host_identity=host_identity,
        name=name,
        source_sha256=final_identity,
        environment_manifest=manifest_result.stdout,
        observations=tuple(observations),
    )


def _require_completed_checkout_identities(
    run_root: Path, proofs: tuple[CheckoutProof, ...]
) -> None:
    for proof in proofs:
        checkout = run_root / proof.name
        _require_directory_identity(
            checkout,
            proof.checkout_identity,
            f"{proof.name} completed checkout",
        )
        _require_directory_identity(
            run_root / host_state_name(proof.name),
            proof.host_identity,
            f"{proof.name} completed host state",
        )
        if _source_identity(checkout) != proof.source_sha256:
            raise CleanRoomError(
                f"{proof.name} source identity changed after checkout completion"
            )


def prove_clean_room(source: Path, work_root: Path, uv: Path) -> dict[str, JSONValue]:
    if not uv.is_file() or not os.access(uv, os.X_OK):
        raise CleanRoomError("clean-room proof requires an explicit executable uv path")
    manifest = build_git_source_manifest(source)
    require_evidence_bounds(manifest.encoded, b"")
    work_root.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="proof-", dir=work_root))
    first_name, second_name = CHECKOUT_NAMES
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(
            _prove_checkout,
            first_name,
            source,
            run_root / first_name,
            uv,
            manifest,
            concurrent=True,
        )
        future_b = executor.submit(
            _prove_checkout,
            second_name,
            source,
            run_root / second_name,
            uv,
            manifest,
            concurrent=False,
        )
        first = future_a.result()
        second = future_b.result()
    _require_completed_checkout_identities(run_root, (first, second))
    if first.environment_manifest != second.environment_manifest:
        raise CleanRoomError("twin checkout environment manifests differ")
    result: dict[str, JSONValue] = {
        "carried_environment_names": [
            "FLARE_HOST_UV",
            "HOME",
            "LANG",
            "LC_ALL",
            "PATH",
            "XDG_CACHE_HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
        ],
        "checkouts": [first.value(), second.value()],
        "source_manifest_entries": len(manifest.document.files),
        "source_manifest_sha256": manifest.sha256,
        "status": "PASS",
    }
    encoded = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()
    require_evidence_bounds(manifest.encoded, encoded)
    _write_source_manifest(run_root, manifest.encoded)
    compact_successful_run(
        run_root,
        source_manifest=manifest.encoded,
        proof=encoded,
    )
    result["proof_directory"] = str(run_root)
    return result


def main(arguments: list[str] | None = None) -> int:
    import sys

    args = list(sys.argv[1:] if arguments is None else arguments)
    if len(args) != 2:
        print(
            "usage: python -m tools.local_execution.clean_room WORK_ROOT UV",
            file=sys.stderr,
        )
        return 2
    try:
        result = prove_clean_room(Path.cwd(), Path(args[0]), Path(args[1]))
    except (
        CleanRoomError,
        CleanRoomRetentionError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        print(f"clean-room=FAIL {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
