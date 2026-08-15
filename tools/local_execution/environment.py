import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from tools.local_execution.profile import HostProfile, TOMLValue

type JSONValue = None | bool | int | str | list[JSONValue] | dict[str, JSONValue]

PROFILE_PATH = "tools/local_execution/host_profile.toml"
CONFIG_PATHS = (
    ".python-version",
    "Makefile",
    "pyproject.toml",
    "uv.lock",
    PROFILE_PATH,
    "flare",
)
PACKAGE_NAME = re.compile(r"^([A-Za-z0-9_.-]+)==([^ ;]+)$")
MANIFEST_NAME = ".flare-environment.json"
MAX_SITE_ENTRIES = 50_000


class EnvironmentError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True, order=True)
class InstalledPackage:
    name: str
    version: str


@dataclass(frozen=True, slots=True)
class EnvironmentManifest:
    profile_id: str
    python_implementation: str
    python_version: str
    uv_version: str
    packages: tuple[InstalledPackage, ...]
    config_sha256: tuple[tuple[str, str], ...]

    def value(self) -> dict[str, JSONValue]:
        return {
            "config_sha256": [
                {"path": path, "sha256": digest} for path, digest in self.config_sha256
            ],
            "packages": [
                {"name": package.name, "version": package.version}
                for package in self.packages
            ],
            "profile_id": self.profile_id,
            "python_implementation": self.python_implementation,
            "python_version": self.python_version,
            "uv_version": self.uv_version,
        }

    def encoded(self) -> bytes:
        return (
            json.dumps(
                self.value(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.encoded()).hexdigest()


def _normalize_package_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _configuration_paths(root: Path) -> tuple[str, ...]:
    package_paths = tuple(
        path.relative_to(root).as_posix()
        for path in sorted((root / "tools/local_execution").glob("*.py"))
    )
    return tuple(sorted((*CONFIG_PATHS, *package_paths), key=str.encode))


def configuration_hashes(root: Path) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for relative in _configuration_paths(root):
        path = root / relative
        if not path.is_file():
            raise EnvironmentError(f"missing bootstrap/config source: {relative}")
        result.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    return tuple(result)


def _required_packages(root: Path) -> tuple[InstalledPackage, ...]:
    value: dict[str, TOMLValue] = tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    project = value.get("project")
    groups = value.get("dependency-groups")
    if not isinstance(project, dict) or not isinstance(groups, dict):
        raise EnvironmentError("pyproject dependency tables are missing")
    dependencies = project.get("dependencies")
    dev = groups.get("dev")
    if not isinstance(dependencies, list) or not isinstance(dev, list):
        raise EnvironmentError("pyproject dependencies must be arrays")
    entries = (*dependencies, *dev)
    result: list[InstalledPackage] = []
    for entry in entries:
        if not isinstance(entry, str):
            raise EnvironmentError("dependency entry must be a string")
        matched = PACKAGE_NAME.fullmatch(entry)
        if matched is None:
            raise EnvironmentError(f"dependency is not exactly pinned: {entry}")
        result.append(
            InstalledPackage(
                _normalize_package_name(matched.group(1)), matched.group(2)
            )
        )
    return tuple(sorted(result))


def _metadata_identity(path: Path) -> InstalledPackage:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_size > 1024 * 1024
    ):
        raise EnvironmentError("project package metadata is unsafe")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise EnvironmentError("project package metadata is unreadable") from error
    values: dict[str, str] = {}
    current: str | None = None
    for line in lines:
        if not line:
            break
        if line[:1] in {" ", "\t"}:
            current = None
            continue
        key, separator, value = line.partition(":")
        current = key if separator else None
        if current not in {"Name", "Version"}:
            continue
        if current in values or not value.strip():
            raise EnvironmentError("project package metadata identity is ambiguous")
        values[current] = value.strip()
    if set(values) != {"Name", "Version"}:
        raise EnvironmentError("project package metadata identity is incomplete")
    return InstalledPackage(_normalize_package_name(values["Name"]), values["Version"])


def _observe_packages(
    environment: Path, profile: HostProfile
) -> tuple[InstalledPackage, ...]:
    major, minor, *_ = profile.python_version.split(".")
    relative = Path("lib") / f"python{major}.{minor}" / "site-packages"
    current = environment
    root_metadata = current.lstat()
    if (
        current.is_symlink()
        or not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid != os.geteuid()
    ):
        raise EnvironmentError("project environment root is unsafe")
    for component in relative.parts:
        current /= component
        metadata = current.lstat()
        if (
            current.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
        ):
            raise EnvironmentError("project site-packages path is unsafe")
    packages: list[InstalledPackage] = []
    entries: list[os.DirEntry[str]] = []
    with os.scandir(current) as iterator:
        for entry in iterator:
            entries.append(entry)
            if len(entries) > MAX_SITE_ENTRIES:
                raise EnvironmentError("project site-packages exceeds its entry bound")
    try:
        ordered = sorted(entries, key=lambda item: item.name.encode("utf-8"))
    except UnicodeError as error:
        raise EnvironmentError("project package path is not canonical UTF-8") from error
    for entry in ordered:
        if not entry.name.endswith(".dist-info"):
            continue
        if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
            raise EnvironmentError("project distribution metadata path is unsafe")
        directory = Path(entry.path)
        metadata = directory.lstat()
        if metadata.st_uid != os.geteuid():
            raise EnvironmentError("project distribution metadata owner is unsafe")
        packages.append(_metadata_identity(directory / "METADATA"))
    result = tuple(sorted(packages))
    names = tuple(package.name for package in result)
    if len(names) != len(set(names)):
        raise EnvironmentError("project package identity is duplicated")
    return result


def observe_uv(uv: Path) -> str:
    completed = subprocess.run(
        [str(uv), "--no-config", "--version"],
        env={
            "HOME": "/nonexistent",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
        },
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    words = completed.stdout.strip().split()
    if completed.returncode != 0 or len(words) < 2 or words[0] != "uv":
        raise EnvironmentError("uv identity/version observation failed")
    return words[1]


def observe_environment(
    root: Path,
    profile: HostProfile,
    environment: Path,
    uv: Path,
) -> EnvironmentManifest:
    return EnvironmentManifest(
        profile_id=profile.profile_id,
        python_implementation=sys.implementation.name,
        python_version=platform.python_version(),
        uv_version=observe_uv(uv),
        packages=_observe_packages(environment, profile),
        config_sha256=configuration_hashes(root),
    )


def validate_environment(
    root: Path,
    profile: HostProfile,
    manifest: EnvironmentManifest,
) -> tuple[str, ...]:
    errors: list[str] = []
    if manifest.python_implementation != profile.python_implementation:
        errors.append(
            "Python implementation mismatch: "
            f"expected={profile.python_implementation}, "
            f"observed={manifest.python_implementation}"
        )
    if manifest.python_version != profile.python_version:
        errors.append(
            f"Python version mismatch: expected={profile.python_version}, "
            f"observed={manifest.python_version}"
        )
    if manifest.uv_version != profile.uv_version:
        errors.append(
            f"uv version mismatch: expected={profile.uv_version}, "
            f"observed={manifest.uv_version}"
        )
    observed = {package.name: package.version for package in manifest.packages}
    for required in _required_packages(root):
        actual = observed.get(required.name)
        if actual != required.version:
            errors.append(
                f"package mismatch {required.name}: expected={required.version}, "
                f"observed={actual or 'missing'}"
            )
    if manifest.config_sha256 != configuration_hashes(root):
        errors.append(
            "bootstrap/config source hashes do not match the current repository"
        )
    return tuple(errors)


def environment_marker_matches(
    environment: Path, manifest: EnvironmentManifest
) -> bool:
    try:
        return (environment / MANIFEST_NAME).read_bytes() == manifest.encoded()
    except OSError:
        return False
