import hashlib
import json
import re
import subprocess
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


def _observe_python(python: Path) -> tuple[str, str, tuple[InstalledPackage, ...]]:
    script = (
        "import importlib.metadata, platform, sys\n"
        "print(sys.implementation.name)\n"
        "print(platform.python_version())\n"
        "for d in sorted(importlib.metadata.distributions(), "
        "key=lambda item: (item.metadata.get('Name') or '').lower()):\n"
        " name=(d.metadata.get('Name') or '').strip()\n"
        " if name: print(name + '\\t' + d.version)\n"
    )
    completed = subprocess.run(
        [str(python), "-I", "-c", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip()[:400]
        raise EnvironmentError(f"project Python observation failed: {detail}")
    lines = completed.stdout.splitlines()
    if len(lines) < 2:
        raise EnvironmentError("project Python observation was incomplete")
    packages: list[InstalledPackage] = []
    for line in lines[2:]:
        name, separator, version = line.partition("\t")
        if not separator or not name or not version:
            raise EnvironmentError("project package observation was malformed")
        packages.append(InstalledPackage(_normalize_package_name(name), version))
    return lines[0], lines[1], tuple(sorted(packages))


def observe_uv(uv: Path) -> str:
    completed = subprocess.run(
        [str(uv), "--version"],
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
    python: Path,
    uv: Path,
) -> EnvironmentManifest:
    implementation, version, packages = _observe_python(python)
    return EnvironmentManifest(
        profile_id=profile.profile_id,
        python_implementation=implementation,
        python_version=version,
        uv_version=observe_uv(uv),
        packages=packages,
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
            f"expected={profile.python_implementation}, observed={manifest.python_implementation}"
        )
    if manifest.python_version != profile.python_version:
        errors.append(
            f"Python version mismatch: expected={profile.python_version}, observed={manifest.python_version}"
        )
    if manifest.uv_version != profile.uv_version:
        errors.append(
            f"uv version mismatch: expected={profile.uv_version}, observed={manifest.uv_version}"
        )
    observed = {package.name: package.version for package in manifest.packages}
    for required in _required_packages(root):
        actual = observed.get(required.name)
        if actual != required.version:
            errors.append(
                f"package mismatch {required.name}: expected={required.version}, observed={actual or 'missing'}"
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
