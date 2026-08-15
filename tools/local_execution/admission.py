from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from tools.local_execution.environment import (
    MANIFEST_NAME,
    configuration_hashes,
    observe_uv,
)
from tools.local_execution.profile import HostProfile

type JSONValue = None | bool | int | str | list[JSONValue] | dict[str, JSONValue]

ADMISSION_NAME = "environment-admission-v1.json"
ADMISSION_DIGEST_NAME = "environment-admission-v1.sha256"
STAGE0_PYTHON_DIGEST_NAME = "stage0-python.sha256"
MAX_MEMBERS = 50_000
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_PATH_BYTES = 512
MAX_RECORD_BYTES = 64 * 1024 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}")
_MODE = re.compile(r"[0-7]{4}")
_SAFE_IMPORT = re.compile(r"import[ \t]+[A-Za-z_][A-Za-z0-9_.]*")
_PYTHON_ALIAS = re.compile(r"(?:python(?:[0-9]+(?:\.[0-9]+)*)?|𝜋thon)")

type FaultHook = Callable[[str], None]


class AdmissionError(RuntimeError):
    pass


def _reject_number(value: str) -> int:
    raise AdmissionError(f"non-integer JSON number is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, JSONValue]]) -> dict[str, JSONValue]:
    result: dict[str, JSONValue] = {}
    for key, value in pairs:
        if key in result:
            raise AdmissionError(f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def _parse_strict_json(raw: bytes) -> JSONValue:
    try:
        text = raw.decode("utf-8", "strict")
        result: JSONValue = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
        return result
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AdmissionError("admission record is not strict UTF-8 JSON") from error


def _canonical_json_bytes(value: JSONValue) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


class EnvironmentState(StrEnum):
    ABSENT = "ABSENT"
    UNADMITTED = "UNADMITTED"
    ADMITTED = "ADMITTED"
    STALE = "STALE"
    CORRUPT = "CORRUPT"


@dataclass(frozen=True, slots=True)
class AdmissionInspection:
    state: EnvironmentState
    detail: str
    marker_sha256: str | None
    duration_seconds: float

    @property
    def admitted(self) -> bool:
        return self.state is EnvironmentState.ADMITTED


def _sha256(path: Path, *, maximum: int = MAX_FILE_BYTES) -> str:
    size = path.stat(follow_symlinks=False).st_size
    if size > maximum:
        raise AdmissionError("regular file exceeds the admission byte bound")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cached_sha256(
    path: Path,
    metadata: os.stat_result,
    cache: dict[tuple[int, int, int, int, int], str],
) -> str:
    identity = (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )
    if identity not in cache:
        cache[identity] = _sha256(path)
    return cache[identity]


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    encoded = value.encode("utf-8", "strict")
    if (
        not value
        or len(encoded) > MAX_PATH_BYTES
        or value != unicodedata.normalize("NFC", value)
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise AdmissionError("environment contains a non-canonical path")
    return value


def _mode(metadata: os.stat_result) -> str:
    return f"{stat.S_IMODE(metadata.st_mode):04o}"


def _require_owned_regular(path: Path, expected_mode: int) -> None:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != expected_mode
    ):
        raise AdmissionError("admission state file metadata is invalid")


def _require_state_directory(state: Path) -> None:
    metadata = state.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise AdmissionError("admission state directory metadata is invalid")


def _tool_value(
    path: Path,
    *,
    version: str,
    confined_to: Path | None,
    implementation: str | None = None,
) -> dict[str, JSONValue]:
    absolute = path.absolute()
    try:
        resolved = absolute.resolve(strict=True)
        confined = confined_to.resolve(strict=True) if confined_to is not None else None
    except (OSError, RuntimeError) as error:
        raise AdmissionError("tool identity path cannot be resolved") from error
    if confined is not None and not _inside(resolved, confined):
        raise AdmissionError("managed Python escapes its declared install root")
    metadata = resolved.stat()
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or not os.access(resolved, os.X_OK)
        or metadata.st_uid not in {0, os.geteuid()}
        or mode & 0o022
    ):
        raise AdmissionError("tool identity metadata is unsafe")
    value: dict[str, JSONValue] = {
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "mode": f"{mode:04o}",
        "path": str(absolute),
        "resolved_path": str(resolved),
        "sha256": _sha256(resolved),
        "uid": metadata.st_uid,
        "version": version,
    }
    if implementation is not None:
        value["implementation"] = implementation
    return value


def _repository_value(root: Path) -> list[JSONValue]:
    return [
        {"path": path, "sha256": digest} for path, digest in configuration_hashes(root)
    ]


def _normalize_mode(path: Path) -> None:
    metadata = path.lstat()
    if metadata.st_uid != os.geteuid():
        raise AdmissionError("candidate contains a foreign-owned member")
    if stat.S_ISLNK(metadata.st_mode):
        return
    if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
        raise AdmissionError("candidate contains a non-regular member")
    path.chmod(stat.S_IMODE(metadata.st_mode) & ~0o022)


def _bounded_entries(directory: Path, remaining: int) -> list[os.DirEntry[str]]:
    entries: list[os.DirEntry[str]] = []
    with os.scandir(directory) as iterator:
        for entry in iterator:
            entries.append(entry)
            if len(entries) > remaining:
                raise AdmissionError("candidate exceeds the admission member bound")
    return entries


def normalize_environment(environment: Path) -> None:
    _normalize_mode(environment)
    pending = [environment]
    visited = 0
    while pending:
        directory = pending.pop()
        entries = _bounded_entries(directory, MAX_MEMBERS - visited)
        for entry in entries:
            visited += 1
            path = Path(entry.path)
            _normalize_mode(path)
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)


def _pth_is_safe(path: Path, environment: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError, UnicodeError:
        return False
    root = environment.resolve(strict=True)
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or _SAFE_IMPORT.fullmatch(line):
            continue
        target = Path(line) if Path(line).is_absolute() else path.parent / line
        try:
            resolved = target.resolve(strict=True)
        except OSError, RuntimeError:
            return False
        if not _inside(resolved, root):
            return False
    return True


def _symlink_value(
    path: Path,
    relative: str,
    environment: Path,
    managed_python: Path,
    metadata: os.stat_result,
    digests: dict[tuple[int, int, int, int, int], str],
) -> dict[str, JSONValue]:
    try:
        target = os.readlink(path)
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise AdmissionError("environment contains a broken symlink") from error
    environment_root = environment.resolve(strict=True)
    managed_resolved = managed_python.resolve(strict=True)
    relative_path = PurePosixPath(relative)
    allowed_python = (
        relative_path.parent == PurePosixPath("bin")
        and _PYTHON_ALIAS.fullmatch(relative_path.name) is not None
        and resolved == managed_resolved
    )
    if not _inside(resolved, environment_root) and not allowed_python:
        raise AdmissionError("environment symlink escapes admitted roots")
    resolved_metadata = resolved.stat()
    if stat.S_ISREG(resolved_metadata.st_mode):
        resolved_digest = _cached_sha256(resolved, resolved_metadata, digests)
    elif stat.S_ISDIR(resolved_metadata.st_mode) and _inside(
        resolved, environment_root
    ):
        resolved_relative = resolved.relative_to(environment_root).as_posix()
        resolved_digest = hashlib.sha256(
            ("directory\0" + resolved_relative).encode("utf-8")
        ).hexdigest()
    else:
        raise AdmissionError("environment symlink target has an invalid type")
    return {
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "kind": "symlink",
        "path": relative,
        "resolved_path": str(resolved),
        "resolved_sha256": resolved_digest,
        "target": target,
        "uid": metadata.st_uid,
    }


def _member_value(
    path: Path,
    environment: Path,
    managed_python: Path,
    device: int,
    digests: dict[tuple[int, int, int, int, int], str],
) -> tuple[dict[str, JSONValue], int]:
    relative = _safe_relative(path.relative_to(environment).as_posix())
    metadata = path.lstat()
    if metadata.st_uid != os.geteuid() or metadata.st_dev != device:
        raise AdmissionError("environment member ownership or device is invalid")
    if stat.S_ISLNK(metadata.st_mode):
        return (
            _symlink_value(
                path,
                relative,
                environment,
                managed_python,
                metadata,
                digests,
            ),
            0,
        )
    mode = stat.S_IMODE(metadata.st_mode)
    if mode & 0o022:
        raise AdmissionError("environment member is group/other writable")
    common: dict[str, JSONValue] = {
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "mode": f"{mode:04o}",
        "path": relative,
        "uid": metadata.st_uid,
    }
    if stat.S_ISDIR(metadata.st_mode):
        return ({**common, "kind": "directory"}, 0)
    if not stat.S_ISREG(metadata.st_mode):
        raise AdmissionError("environment contains a non-regular member")
    if metadata.st_nlink != 1:
        raise AdmissionError("environment regular file has an external hardlink")
    if metadata.st_size > MAX_FILE_BYTES:
        raise AdmissionError("environment file exceeds the admission byte bound")
    if path.suffix == ".pth" and not _pth_is_safe(path, environment):
        raise AdmissionError("environment contains an unsafe .pth import path")
    digest = _cached_sha256(path, metadata, digests)
    relative_path = PurePosixPath(relative)
    if (
        relative_path.parent == PurePosixPath("bin")
        and _PYTHON_ALIAS.fullmatch(relative_path.name) is not None
    ):
        managed_resolved = managed_python.resolve(strict=True)
        managed_metadata = managed_resolved.stat()
        if not os.access(path, os.X_OK) or digest != _cached_sha256(
            managed_resolved, managed_metadata, digests
        ):
            raise AdmissionError("project Python bytes differ from managed Python")
    return (
        {
            **common,
            "bytes": metadata.st_size,
            "kind": "file",
            "links": metadata.st_nlink,
            "sha256": digest,
        },
        metadata.st_size,
    )


def _environment_members(
    environment: Path, managed_python: Path, device: int
) -> list[JSONValue]:
    pending = [environment]
    paths: list[Path] = []
    while pending:
        directory = pending.pop()
        entries = _bounded_entries(directory, MAX_MEMBERS - len(paths))
        for entry in entries:
            paths.append(Path(entry.path))
            if entry.is_dir(follow_symlinks=False):
                pending.append(Path(entry.path))
    members: list[JSONValue] = []
    total_bytes = 0
    digests: dict[tuple[int, int, int, int, int], str] = {}
    for path in sorted(
        paths,
        key=lambda item: item.relative_to(environment).as_posix().encode("utf-8"),
    ):
        member, size = _member_value(path, environment, managed_python, device, digests)
        total_bytes += size
        if total_bytes > MAX_TOTAL_BYTES:
            raise AdmissionError("environment exceeds the total admission byte bound")
        members.append(member)
    return members


def _environment_value(environment: Path, managed_python: Path) -> dict[str, JSONValue]:
    metadata = environment.lstat()
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or environment.is_symlink()
        or metadata.st_uid != os.geteuid()
        or mode & 0o022
    ):
        raise AdmissionError("environment root metadata is invalid")
    marker = environment / MANIFEST_NAME
    marker_metadata = marker.lstat()
    if not stat.S_ISREG(marker_metadata.st_mode) or marker.is_symlink():
        raise AdmissionError("environment marker is missing or invalid")
    return {
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "marker_sha256": _sha256(marker),
        "members": _environment_members(environment, managed_python, metadata.st_dev),
        "mode": f"{mode:04o}",
        "uid": metadata.st_uid,
    }


def validate_environment_tree(environment: Path, managed_python: Path) -> None:
    _environment_value(environment, managed_python)


def build_admission_record(
    root: Path,
    profile: HostProfile,
    environment: Path,
    uv: Path,
    managed_python: Path,
) -> dict[str, JSONValue]:
    uv_version = observe_uv(uv)
    if uv_version != profile.uv_version:
        raise AdmissionError("uv identity differs from the supported profile")
    stage0_tree = _strict_digest(
        profile.path(root, profile.project_state) / STAGE0_PYTHON_DIGEST_NAME
    )
    return {
        "environment": _environment_value(environment, managed_python),
        "environment_path": profile.project_environment,
        "managed_python_tree_sha256": stage0_tree,
        "managed_python": _tool_value(
            managed_python,
            version=profile.python_version,
            confined_to=profile.path(root, profile.python_install_dir),
            implementation=profile.python_implementation,
        ),
        "profile_id": profile.profile_id,
        "repository_config": _repository_value(root),
        "schema_version": "1.0",
        "state": EnvironmentState.ADMITTED.value,
        "uv": _tool_value(uv, version=uv_version, confined_to=None),
    }


def _atomic_write(path: Path, payload: bytes) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_path)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_admission(
    state: Path,
    record: dict[str, JSONValue],
    fault_hook: FaultHook | None = None,
) -> None:
    encoded = _canonical_json_bytes(record)
    if len(encoded) > MAX_RECORD_BYTES:
        raise AdmissionError("admission record exceeds its byte bound")
    record_path = state / ADMISSION_NAME
    digest_path = state / ADMISSION_DIGEST_NAME
    record_temporary: Path | None = None
    digest_temporary: Path | None = None
    try:
        record_temporary = _atomic_write(record_path, encoded)
        digest_temporary = _atomic_write(
            digest_path,
            (hashlib.sha256(encoded).hexdigest() + "\n").encode("ascii"),
        )
        digest_path.unlink(missing_ok=True)
        os.replace(record_temporary, record_path)
        record_temporary = None
        _fsync_directory(state)
        if fault_hook is not None:
            fault_hook("before-admission-publication")
        os.replace(digest_temporary, digest_path)
        digest_temporary = None
        _fsync_directory(state)
        if fault_hook is not None:
            fault_hook("after-admission-publication")
    finally:
        if record_temporary is not None:
            record_temporary.unlink(missing_ok=True)
        if digest_temporary is not None:
            digest_temporary.unlink(missing_ok=True)


def _strict_digest(path: Path) -> str:
    _require_owned_regular(path, 0o600)
    if path.stat(follow_symlinks=False).st_size != 65:
        raise AdmissionError("admission digest size is invalid")
    raw = path.read_bytes()
    try:
        text = raw.decode("ascii", "strict")
    except UnicodeError as error:
        raise AdmissionError("admission digest is not ASCII") from error
    if not text.endswith("\n") or text.count("\n") != 1:
        raise AdmissionError("admission digest framing is invalid")
    value = text[:-1]
    if _DIGEST.fullmatch(value) is None:
        raise AdmissionError("admission digest grammar is invalid")
    return value


def _mapping(value: JSONValue, label: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise AdmissionError(f"{label} is not an object")
    return value


def _require_keys(value: dict[str, JSONValue], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise AdmissionError(f"{label} keys are invalid")


def _string(value: dict[str, JSONValue], key: str, label: str) -> str:
    item = value[key]
    if type(item) is not str or not item:
        raise AdmissionError(f"{label} {key} is not a non-empty string")
    return item


def _integer(value: dict[str, JSONValue], key: str, label: str) -> int:
    item = value[key]
    if type(item) is not int or item < 0:
        raise AdmissionError(f"{label} {key} is not a non-negative integer")
    return item


def _digest_value(value: dict[str, JSONValue], key: str, label: str) -> None:
    if _DIGEST.fullmatch(_string(value, key, label)) is None:
        raise AdmissionError(f"{label} {key} is not a SHA-256 digest")


def _mode_value(value: dict[str, JSONValue], key: str, label: str) -> None:
    if _MODE.fullmatch(_string(value, key, label)) is None:
        raise AdmissionError(f"{label} {key} is not an octal mode")


def _validate_member_shape(value: JSONValue) -> None:
    member = _mapping(value, "admission member")
    kind = member.get("kind")
    common = {"device", "inode", "kind", "path", "uid"}
    if kind == "directory":
        expected = common | {"mode"}
    elif kind == "file":
        expected = common | {"bytes", "links", "mode", "sha256"}
    elif kind == "symlink":
        expected = common | {"resolved_path", "resolved_sha256", "target"}
    else:
        raise AdmissionError("admission member kind is invalid")
    _require_keys(member, expected, "admission member")
    _safe_relative(_string(member, "path", "admission member"))
    for key in ("device", "inode", "uid"):
        _integer(member, key, "admission member")
    if kind in {"directory", "file"}:
        _mode_value(member, "mode", "admission member")
    if kind == "file":
        _integer(member, "bytes", "admission member")
        _integer(member, "links", "admission member")
        _digest_value(member, "sha256", "admission member")
    if kind == "symlink":
        for key in ("resolved_path", "target"):
            _string(member, key, "admission member")
        _digest_value(member, "resolved_sha256", "admission member")


def _validate_tool_shape(value: JSONValue, label: str, *, managed: bool) -> None:
    tool = _mapping(value, label)
    keys = {
        "device",
        "inode",
        "mode",
        "path",
        "resolved_path",
        "sha256",
        "uid",
        "version",
    }
    if managed:
        keys.add("implementation")
    _require_keys(tool, keys, label)
    for key in ("device", "inode", "uid"):
        _integer(tool, key, label)
    _mode_value(tool, "mode", label)
    _digest_value(tool, "sha256", label)
    for key in ("path", "resolved_path", "version"):
        _string(tool, key, label)
    if managed:
        _string(tool, "implementation", label)


def _validate_record_shape(value: JSONValue) -> dict[str, JSONValue]:
    record = _mapping(value, "admission record")
    _require_keys(
        record,
        {
            "environment",
            "environment_path",
            "managed_python",
            "managed_python_tree_sha256",
            "profile_id",
            "repository_config",
            "schema_version",
            "state",
            "uv",
        },
        "admission record",
    )
    environment = _mapping(record["environment"], "admission environment")
    _require_keys(
        environment,
        {"device", "inode", "marker_sha256", "members", "mode", "uid"},
        "admission environment",
    )
    members = environment["members"]
    if not isinstance(members, list) or len(members) > MAX_MEMBERS:
        raise AdmissionError("admission members are not an array")
    paths: list[str] = []
    for member in members:
        _validate_member_shape(member)
        paths.append(_string(_mapping(member, "admission member"), "path", "member"))
    if paths != sorted(paths, key=str.encode) or len(paths) != len(set(paths)):
        raise AdmissionError("admission members are not uniquely bytewise sorted")
    for key in ("device", "inode", "uid"):
        _integer(environment, key, "admission environment")
    _mode_value(environment, "mode", "admission environment")
    _digest_value(environment, "marker_sha256", "admission environment")
    _validate_tool_shape(record["uv"], "uv identity", managed=False)
    _validate_tool_shape(
        record["managed_python"], "managed Python identity", managed=True
    )
    _digest_value(record, "managed_python_tree_sha256", "managed Python tree identity")
    repository = record["repository_config"]
    if not isinstance(repository, list) or len(repository) > 10_000:
        raise AdmissionError("repository config is not a bounded array")
    repository_paths: list[str] = []
    for item in repository:
        entry = _mapping(item, "repository config entry")
        _require_keys(entry, {"path", "sha256"}, "repository config entry")
        repository_paths.append(
            _safe_relative(_string(entry, "path", "repository config entry"))
        )
        _digest_value(entry, "sha256", "repository config entry")
    if repository_paths != sorted(repository_paths, key=str.encode) or len(
        repository_paths
    ) != len(set(repository_paths)):
        raise AdmissionError("repository config is not uniquely bytewise sorted")
    _safe_relative(_string(record, "environment_path", "admission record"))
    _string(record, "profile_id", "admission record")
    if record["schema_version"] != "1.0" or record["state"] != "ADMITTED":
        raise AdmissionError("admission record version or state is invalid")
    return record


def _record(path: Path, digest_path: Path) -> dict[str, JSONValue]:
    _require_owned_regular(path, 0o600)
    if path.stat().st_size > MAX_RECORD_BYTES:
        raise AdmissionError("admission record exceeds its byte bound")
    expected = _strict_digest(digest_path)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise AdmissionError("admission record digest mismatch")
    value = _parse_strict_json(raw)
    if _canonical_json_bytes(value) != raw:
        raise AdmissionError("admission record is not canonical JSON")
    return _validate_record_shape(value)


def _static_value(
    root: Path, profile: HostProfile, uv: Path, managed_python: Path
) -> dict[str, JSONValue]:
    uv_version = observe_uv(uv)
    if uv_version != profile.uv_version:
        raise AdmissionError("current uv differs from the supported profile")
    return {
        "environment_path": profile.project_environment,
        "managed_python_tree_sha256": _strict_digest(
            profile.path(root, profile.project_state) / STAGE0_PYTHON_DIGEST_NAME
        ),
        "managed_python": _tool_value(
            managed_python,
            version=profile.python_version,
            confined_to=profile.path(root, profile.python_install_dir),
            implementation=profile.python_implementation,
        ),
        "profile_id": profile.profile_id,
        "repository_config": _repository_value(root),
        "schema_version": "1.0",
        "state": EnvironmentState.ADMITTED.value,
        "uv": _tool_value(uv, version=uv_version, confined_to=None),
    }


def _result(
    state: EnvironmentState, detail: str, marker: str | None, started: float
) -> AdmissionInspection:
    return AdmissionInspection(state, detail, marker, time.monotonic() - started)


def _environment_result(
    record: dict[str, JSONValue],
    environment: Path,
    managed_python: Path,
    started: float,
) -> AdmissionInspection:
    try:
        current = _environment_value(environment, managed_python)
    except (AdmissionError, OSError, UnicodeError) as error:
        return _result(EnvironmentState.CORRUPT, str(error), None, started)
    if record["environment"] != current:
        return _result(
            EnvironmentState.CORRUPT,
            "environment bytes or metadata differ from admission state",
            None,
            started,
        )
    marker = current["marker_sha256"]
    if not isinstance(marker, str):
        return _result(
            EnvironmentState.CORRUPT,
            "environment marker identity is invalid",
            None,
            started,
        )
    return _result(
        EnvironmentState.ADMITTED,
        "environment bytes match current repository and toolchain truth",
        marker,
        started,
    )


def inspect_admission(
    root: Path,
    profile: HostProfile,
    uv: Path,
    managed_python: Path,
) -> AdmissionInspection:
    started = time.monotonic()
    environment = profile.path(root, profile.project_environment)
    state = profile.path(root, profile.project_state)
    record_path = state / ADMISSION_NAME
    digest_path = state / ADMISSION_DIGEST_NAME
    stage0_digest = state / STAGE0_PYTHON_DIGEST_NAME
    environment_present = environment.exists() or environment.is_symlink()
    record_present = record_path.exists() or record_path.is_symlink()
    digest_present = digest_path.exists() or digest_path.is_symlink()
    stage0_present = stage0_digest.exists() or stage0_digest.is_symlink()
    admission_present = record_present or digest_present
    if not environment_present and not admission_present:
        return _result(EnvironmentState.ABSENT, "environment is absent", None, started)
    if not environment_present:
        return _result(
            EnvironmentState.CORRUPT,
            "admission record exists without an environment",
            None,
            started,
        )
    if not (record_present and digest_present and stage0_present):
        return _result(
            EnvironmentState.UNADMITTED,
            "environment has no complete admission bundle",
            None,
            started,
        )
    try:
        _require_state_directory(state)
        _strict_digest(stage0_digest)
        record = _record(record_path, digest_path)
    except (AdmissionError, OSError, RuntimeError, UnicodeError, ValueError) as error:
        return _result(EnvironmentState.CORRUPT, str(error), None, started)
    try:
        current_static = _static_value(root, profile, uv, managed_python)
    except (
        AdmissionError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        return _result(EnvironmentState.STALE, str(error), None, started)
    recorded_static = {
        key: value for key, value in record.items() if key != "environment"
    }
    if recorded_static != current_static:
        return _result(
            EnvironmentState.STALE,
            "repository or toolchain identity differs from admission state",
            None,
            started,
        )
    return _environment_result(record, environment, managed_python, started)
