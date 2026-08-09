import json
import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from tools.project_state.model import JSONValue
from tools.quality.source_manifest import (
    SourceManifest,
    build_git_source_manifest,
    build_source_manifest,
)

MAX_OBSERVATION_BYTES = 12_000


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


def _run(
    label: str,
    argv: tuple[str, ...],
    root: Path,
    environment: dict[str, str],
    *,
    expected: frozenset[int] = frozenset({0}),
) -> CommandObservation:
    started = time.monotonic()
    completed = subprocess.run(
        argv,
        cwd=root,
        env=environment,
        capture_output=True,
        check=False,
        timeout=1_200,
    )
    observation = CommandObservation(
        label,
        completed.returncode,
        _bound(completed.stdout),
        _bound(completed.stderr),
        time.monotonic() - started,
    )
    if completed.returncode not in expected:
        raise CleanRoomError(
            f"{label} returned {completed.returncode}; "
            f"stdout={observation.stdout!r}; stderr={observation.stderr!r}"
        )
    return observation


def _materialize(source: Path, target: Path, manifest: SourceManifest) -> None:
    target.mkdir(parents=True)
    for entry in manifest.document.files:
        source_path = source / entry.path
        target_path = target / entry.path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if entry.kind == "symlink":
            target_path.symlink_to(os.readlink(source_path))
        else:
            shutil.copy2(source_path, target_path)


def _source_identity(root: Path) -> str:
    generated_roots = {".cache", ".flare", ".venv"}
    generated_parts = {".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
    paths = tuple(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if (path.is_file() or path.is_symlink())
        and path.relative_to(root).parts[0] not in generated_roots
        and not generated_parts.intersection(path.relative_to(root).parts)
        and path.suffix != ".pyc"
    )
    return build_source_manifest(root, paths).sha256


def _isolated_environment(root: Path, uv: Path) -> dict[str, str]:
    isolated = root.parent / f"{root.name}-host-state"
    home = isolated / "home"
    xdg_cache = isolated / "xdg-cache"
    xdg_config = isolated / "xdg-config"
    xdg_data = isolated / "xdg-data"
    for path in (home, xdg_cache, xdg_config, xdg_data):
        path.mkdir(parents=True)
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
            "concurrent bootstrap did not converge as exactly one CREATED and one REUSED"
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
    environment = _isolated_environment(target, uv)
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
    manifest_result = subprocess.run(
        ("./flare", "environment-manifest"),
        cwd=target,
        env=environment,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if manifest_result.returncode != 0:
        raise CleanRoomError(
            f"{name} environment manifest failed: {_bound(manifest_result.stderr)}"
        )
    final_identity = _source_identity(target)
    if final_identity != initial_identity:
        raise CleanRoomError(f"{name} bootstrap mutated source truth")
    return CheckoutProof(
        name, final_identity, manifest_result.stdout, tuple(observations)
    )


def prove_clean_room(source: Path, work_root: Path, uv: Path) -> dict[str, JSONValue]:
    if not uv.is_file() or not os.access(uv, os.X_OK):
        raise CleanRoomError("clean-room proof requires an explicit executable uv path")
    manifest = build_git_source_manifest(source)
    work_root.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="proof-", dir=work_root))
    (run_root / "SOURCE_MANIFEST.json").write_bytes(manifest.encoded)
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(
            _prove_checkout,
            "checkout-a",
            source,
            run_root / "checkout-a",
            uv,
            manifest,
            concurrent=True,
        )
        future_b = executor.submit(
            _prove_checkout,
            "checkout-b",
            source,
            run_root / "checkout-b",
            uv,
            manifest,
            concurrent=False,
        )
        first = future_a.result()
        second = future_b.result()
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
    (run_root / "proof.json").write_bytes(encoded)
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
    except (CleanRoomError, OSError, subprocess.SubprocessError) as error:
        print(f"clean-room=FAIL {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
