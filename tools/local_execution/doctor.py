import os
import platform
import shutil
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from tools.local_execution.environment import (
    EnvironmentError,
    EnvironmentManifest,
    environment_marker_matches,
    observe_environment,
    validate_environment,
)
from tools.local_execution.model import CheckStatus, DoctorReport, Observation
from tools.local_execution.profile import HostProfile, TOMLValue


@dataclass(frozen=True, slots=True)
class PlatformFacts:
    os: str
    release_id: str
    release_version: str
    architecture: str


def detect_platform() -> PlatformFacts:
    fields: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                fields[key] = value.strip().strip('"')
    except OSError:
        pass
    return PlatformFacts(
        os=platform.system(),
        release_id=fields.get("ID", "unknown"),
        release_version=fields.get("VERSION_ID", "unknown"),
        architecture=platform.machine(),
    )


def _within(path: Path, parent: Path) -> bool:
    try:
        path.absolute().relative_to(parent.absolute())
    except ValueError:
        return False
    return True


def _configuration_observations(
    root: Path, profile: HostProfile
) -> tuple[Observation, ...]:
    observations: list[Observation] = []
    expected_files = (".python-version", "pyproject.toml", "uv.lock")
    missing = tuple(
        relative for relative in expected_files if not (root / relative).is_file()
    )
    observations.append(
        Observation(
            "repository_prerequisites",
            CheckStatus.FAIL if missing else CheckStatus.PASS,
            "missing=" + ",".join(missing) if missing else "required files present",
            True,
        )
    )
    if missing:
        return tuple(observations)
    python_declared = (root / ".python-version").read_text(encoding="utf-8").strip()
    value: dict[str, TOMLValue] = tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    project = value.get("project")
    tool = value.get("tool")
    requires = project.get("requires-python") if isinstance(project, dict) else None
    uv_table = tool.get("uv") if isinstance(tool, dict) else None
    ruff_table = tool.get("ruff") if isinstance(tool, dict) else None
    mypy_table = tool.get("mypy") if isinstance(tool, dict) else None
    version_parts = profile.python_version.split(".")
    version_is_valid = (
        len(version_parts) >= 2
        and version_parts[0].isdigit()
        and version_parts[1].isdigit()
    )
    python_range: str | None
    ruff_target: str | None
    mypy_target: str | None
    if version_is_valid:
        major, minor = int(version_parts[0]), int(version_parts[1])
        python_range = f">={major}.{minor},<{major}.{minor + 1}"
        ruff_target = f"py{major}{minor}"
        mypy_target = f"{major}.{minor}"
    else:
        python_range = None
        ruff_target = None
        mypy_target = None
    aligned = (
        python_declared == profile.python_version
        and requires == python_range
        and isinstance(uv_table, dict)
        and uv_table.get("required-version") == f"=={profile.uv_version}"
        and isinstance(ruff_table, dict)
        and ruff_table.get("target-version") == ruff_target
        and isinstance(mypy_table, dict)
        and mypy_table.get("python_version") == mypy_target
    )
    observations.append(
        Observation(
            "version_contract",
            CheckStatus.PASS if aligned else CheckStatus.FAIL,
            f"required Python={profile.python_version}, uv={profile.uv_version}",
            True,
        )
    )
    return tuple(observations)


def _command_available(command: str, uv: Path) -> bool:
    if command == "uv":
        return uv.is_file() and os.access(uv, os.X_OK)
    if command.startswith("/"):
        return Path(command).is_file() and os.access(command, os.X_OK)
    return shutil.which(command) is not None


def _host_observations(
    profile: HostProfile,
    uv: Path,
    actual: PlatformFacts,
) -> list[Observation]:
    host_matches = (
        actual.os == profile.os
        and actual.release_id == profile.os_release_id
        and actual.release_version == profile.os_release_version
        and actual.architecture == profile.architecture
    )
    observations = [
        Observation(
            "host_profile",
            CheckStatus.PASS if host_matches else CheckStatus.FAIL,
            (
                f"detected={actual.os}/{actual.release_id}-"
                f"{actual.release_version}/{actual.architecture}; "
                f"supported={profile.os}/{profile.os_release_id}-"
                f"{profile.os_release_version}/{profile.architecture}"
            ),
            True,
        )
    ]
    for command in profile.required_host_commands:
        available = _command_available(command, uv)
        observations.append(
            Observation(
                f"host_command:{command}",
                CheckStatus.PASS if available else CheckStatus.FAIL,
                "declared host trust root available"
                if available
                else "declared host trust root missing",
                True,
            )
        )
    return observations


def _bootstrap_observations(profile: HostProfile) -> list[Observation]:
    configured_sources = tuple(
        name
        for name in profile.external_package_source_environment
        if os.environ.get(name)
    )
    return [
        Observation(
            "package_source_configuration",
            CheckStatus.PASS,
            (
                "configured variable names=" + ",".join(configured_sources)
                if configured_sources
                else "uv default public source; no external source variables configured"
            ),
            False,
        ),
        Observation(
            "bootstrap_integrity",
            CheckStatus.PASS,
            "authorities=" + ",".join(profile.integrity_authorities),
            True,
        ),
    ]


def _environment_status(
    root: Path,
    profile: HostProfile,
    uv: Path,
    python: Path,
) -> tuple[EnvironmentManifest | None, tuple[str, ...]]:
    environment_root = profile.path(root, profile.project_environment)
    try:
        manifest = observe_environment(root, profile, environment_root, uv)
        environment_errors = validate_environment(root, profile, manifest)
        if not environment_marker_matches(environment_root, manifest):
            environment_errors = (
                *environment_errors,
                "project environment marker is missing, corrupt, or stale",
            )
    except (EnvironmentError, OSError, TimeoutError) as error:
        return None, (str(error),)
    return manifest, environment_errors


def _environment_observations(
    root: Path,
    profile: HostProfile,
    uv: Path,
    python: Path,
) -> list[Observation]:
    environment_root = profile.path(root, profile.project_environment)
    manifest, environment_errors = _environment_status(root, profile, uv, python)
    project_python = environment_root / "bin/python"
    provenance_ok = (
        _within(project_python, environment_root)
        and project_python.is_file()
        and os.access(project_python, os.X_OK)
    )
    return [
        Observation(
            "python_provenance",
            CheckStatus.PASS if provenance_ok else CheckStatus.FAIL,
            "project-local managed runtime"
            if provenance_ok
            else "runtime resolves outside declared project-local roots",
            True,
        ),
        Observation(
            "python_runtime",
            (
                CheckStatus.PASS
                if manifest is not None
                and manifest.python_implementation == profile.python_implementation
                and manifest.python_version == profile.python_version
                else CheckStatus.FAIL
            ),
            (
                f"observed={manifest.python_implementation}-{manifest.python_version}; "
                "executable_role=project_environment/bin/python"
                if manifest is not None
                else "observed runtime unavailable"
            ),
            True,
        ),
        Observation(
            "uv_identity",
            (
                CheckStatus.PASS
                if manifest is not None and manifest.uv_version == profile.uv_version
                else CheckStatus.FAIL
            ),
            (
                f"observed={manifest.uv_version}; provenance=explicit host prerequisite"
                if manifest is not None
                else "observed uv unavailable"
            ),
            True,
        ),
        Observation(
            "project_environment",
            CheckStatus.PASS
            if manifest is not None and not environment_errors
            else CheckStatus.FAIL,
            "; ".join(environment_errors)
            if environment_errors
            else (
                f"manifest={manifest.sha256 if manifest is not None else 'unavailable'}"
            ),
            True,
        ),
    ]


def _allure_observation(optional_path: str | None) -> Observation:
    search_path = os.environ.get("PATH", "") if optional_path is None else optional_path
    renderer = shutil.which("allure", path=search_path)
    return Observation(
        "allure_renderer",
        CheckStatus.PASS if renderer is not None else CheckStatus.OPTIONAL_MISSING,
        "available"
        if renderer is not None
        else "HTML rendering is optional; raw evidence remains supported",
        False,
    )


def inspect_doctor(
    root: Path,
    profile: HostProfile,
    uv: Path,
    python: Path,
    *,
    facts: PlatformFacts | None = None,
    optional_path: str | None = None,
) -> DoctorReport:
    actual = detect_platform() if facts is None else facts
    observations = _host_observations(profile, uv, actual)
    observations.extend(_configuration_observations(root, profile))
    observations.extend(_bootstrap_observations(profile))
    observations.extend(_environment_observations(root, profile, uv, python))
    observations.append(_allure_observation(optional_path))
    return DoctorReport(profile.profile_id, tuple(observations))


def doctor_command(root: Path, profile: HostProfile, uv: Path) -> int:
    report = inspect_doctor(root, profile, uv, Path(sys.executable))
    sys.stdout.write(report.render())
    return 0 if report.passed else 1
