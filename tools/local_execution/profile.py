import tomllib
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path, PurePosixPath

type TOMLScalar = bool | int | float | str | date | datetime | time | None
type TOMLValue = TOMLScalar | list[TOMLValue] | dict[str, TOMLValue]


class ProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class HostProfile:
    profile_id: str
    os: str
    os_release_id: str
    os_release_version: str
    architecture: str
    python_implementation: str
    python_version: str
    uv_version: str
    project_environment: str
    project_state: str
    python_install_dir: str
    uv_cache: str
    required_host_commands: tuple[str, ...]
    exact_version_host_commands: tuple[str, ...]
    discoverable_host_commands: tuple[str, ...]
    project_local_reconstruction: tuple[str, ...]
    integrity_authorities: tuple[str, ...]
    external_package_source_environment: tuple[str, ...]
    explicitly_untrusted_host_state: tuple[str, ...]
    optional_capabilities: tuple[str, ...]

    def path(self, root: Path, relative: str) -> Path:
        if not _safe_relative_path(relative):
            raise ProfileError(f"unsafe project-local path: {relative!r}")
        return root / relative


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and path.as_posix() == value
        and not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _string(table: dict[str, TOMLValue], name: str) -> str:
    value = table.get(name)
    if not isinstance(value, str) or not value:
        raise ProfileError(f"host profile field {name!r} must be a non-empty string")
    return value


def _strings(table: dict[str, TOMLValue], name: str) -> tuple[str, ...]:
    value = table.get(name)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ProfileError(f"host profile field {name!r} must be a string array")
    result = tuple(item for item in value if isinstance(item, str))
    if len(result) != len(set(result)):
        raise ProfileError(f"host profile field {name!r} contains duplicates")
    return result


def load_profile(path: Path) -> HostProfile:
    try:
        value: dict[str, TOMLValue] = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ProfileError(f"unable to read host profile: {error}") from error
    profile = HostProfile(
        profile_id=_string(value, "profile_id"),
        os=_string(value, "os"),
        os_release_id=_string(value, "os_release_id"),
        os_release_version=_string(value, "os_release_version"),
        architecture=_string(value, "architecture"),
        python_implementation=_string(value, "python_implementation"),
        python_version=_string(value, "python_version"),
        uv_version=_string(value, "uv_version"),
        project_environment=_string(value, "project_environment"),
        project_state=_string(value, "project_state"),
        python_install_dir=_string(value, "python_install_dir"),
        uv_cache=_string(value, "uv_cache"),
        required_host_commands=_strings(value, "required_host_commands"),
        exact_version_host_commands=_strings(value, "exact_version_host_commands"),
        discoverable_host_commands=_strings(value, "discoverable_host_commands"),
        project_local_reconstruction=_strings(value, "project_local_reconstruction"),
        integrity_authorities=_strings(value, "integrity_authorities"),
        external_package_source_environment=_strings(
            value, "external_package_source_environment"
        ),
        explicitly_untrusted_host_state=_strings(
            value, "explicitly_untrusted_host_state"
        ),
        optional_capabilities=_strings(value, "optional_capabilities"),
    )
    for relative in (
        profile.project_environment,
        profile.project_state,
        profile.python_install_dir,
        profile.uv_cache,
    ):
        if not _safe_relative_path(relative):
            raise ProfileError(f"unsafe project-local path: {relative!r}")
    required = set(profile.required_host_commands)
    exact = set(profile.exact_version_host_commands)
    discoverable = set(profile.discoverable_host_commands)
    if exact & discoverable or exact | discoverable != required:
        raise ProfileError(
            "exact-version and discoverable host commands must partition the trust root"
        )
    return profile
