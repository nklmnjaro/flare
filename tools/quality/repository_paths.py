from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING or __package__:
    from tools.canonical_paths import (
        CanonicalPathError,
        canonical_relative_posix_path,
    )
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from canonical_paths import (
        CanonicalPathError,
        canonical_relative_posix_path,
    )

EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".cache",
        ".flare",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tmp",
        ".venv",
        "__pycache__",
        "generated",
        "node_modules",
        "third_party",
        "vendor",
    }
)


class GitPathMode(StrEnum):
    TRACKED = "tracked"
    TRACKED_AND_UNTRACKED = "tracked-and-untracked"


class RepositoryPathError(ValueError):
    pass


def has_git_metadata(root: Path) -> bool:
    try:
        metadata = (root / ".git").lstat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise RepositoryPathError("unable to inspect Git metadata") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise RepositoryPathError("Git metadata is a symlink")
    if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
        raise RepositoryPathError("Git metadata has an unsupported file type")
    return True


def _validate_git_repository_root(root: Path, git: str) -> None:
    result = subprocess.run(
        (git, "-C", str(root), "rev-parse", "--show-toplevel"),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    stdout = result.stdout
    if (
        result.returncode != 0
        or not stdout.endswith(b"\n")
        or b"\n" in stdout[:-1]
        or b"\0" in stdout
    ):
        raise RepositoryPathError("unable to resolve Git repository root")
    try:
        observed = Path(os.fsdecode(stdout[:-1])).resolve(strict=True)
        expected = root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RepositoryPathError("unable to resolve Git repository root") from error
    if observed != expected:
        raise RepositoryPathError("Git metadata does not belong to repository root")


def validate_repository_path(value: str | Path) -> Path:
    rendered = value.as_posix() if isinstance(value, Path) else value
    try:
        canonical = canonical_relative_posix_path(
            rendered,
            label="repository path",
        )
    except CanonicalPathError as error:
        raise RepositoryPathError(str(error)) from error
    return Path(*canonical.split("/"))


def _git_paths(root: Path, mode: GitPathMode) -> tuple[Path, ...]:
    git = shutil.which("git")
    if git is None:
        raise RepositoryPathError("Git is required to inspect repository paths")
    _validate_git_repository_root(root, git)
    arguments = [git, "-C", str(root), "ls-files", "--cached"]
    if mode is GitPathMode.TRACKED_AND_UNTRACKED:
        arguments.extend(("--others", "--exclude-standard"))
    arguments.append("-z")
    result = subprocess.run(
        arguments,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise RepositoryPathError("unable to read Git index")
    if result.stdout and not result.stdout.endswith(b"\0"):
        raise RepositoryPathError("Git returned a malformed path list")
    paths: list[Path] = []
    seen: set[str] = set()
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        rendered = os.fsdecode(raw_path)
        try:
            path = validate_repository_path(rendered)
        except RepositoryPathError as error:
            raise RepositoryPathError(
                "Git returned an invalid repository path"
            ) from error
        canonical = path.as_posix()
        if canonical in seen:
            raise RepositoryPathError("Git returned a duplicate repository path")
        seen.add(canonical)
        paths.append(path)
    return tuple(sorted(paths, key=Path.as_posix))


def _walk_paths(
    root: Path,
    *,
    exclude_directories: bool,
) -> tuple[Path, ...]:
    paths: list[Path] = []

    def fail_walk(_error: OSError) -> None:
        raise RepositoryPathError("unable to walk source tree")

    def source_metadata(path: Path) -> os.stat_result:
        try:
            return path.lstat()
        except OSError as error:
            raise RepositoryPathError("unable to inspect source tree") from error

    for directory, directory_names, file_names in os.walk(
        root,
        topdown=True,
        onerror=fail_walk,
        followlinks=False,
    ):
        current = Path(directory)
        kept_directories: list[str] = []
        for name in sorted(directory_names):
            relative = validate_repository_path((current / name).relative_to(root))
            path = current / name
            metadata = source_metadata(path)
            if stat.S_ISDIR(metadata.st_mode):
                if not exclude_directories or name not in EXCLUDED_DIRECTORY_NAMES:
                    kept_directories.append(name)
            else:
                paths.append(relative)
        directory_names[:] = kept_directories
        for name in sorted(file_names):
            relative = validate_repository_path((current / name).relative_to(root))
            if not stat.S_ISDIR(source_metadata(current / name).st_mode):
                paths.append(relative)
    return tuple(sorted(set(paths), key=Path.as_posix))


def repository_paths(
    root: Path,
    git_mode: GitPathMode,
    *,
    exclude_directories: bool = False,
) -> tuple[Path, ...]:
    if has_git_metadata(root):
        paths = _git_paths(root, git_mode)
        if exclude_directories:
            return tuple(
                path
                for path in paths
                if not any(part in EXCLUDED_DIRECTORY_NAMES for part in path.parts[:-1])
            )
        return paths
    return _walk_paths(root, exclude_directories=exclude_directories)


def regular_repository_file(
    root: Path,
    relative: Path,
    *,
    missing_ok: bool = False,
) -> Path | None:
    relative = validate_repository_path(relative)
    current = root
    for part in relative.parts[:-1]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            if missing_ok:
                return None
            raise RepositoryPathError(
                f"repository path is missing: {relative.as_posix()}"
            ) from None
        except OSError as error:
            raise RepositoryPathError(
                f"unable to inspect repository path: {relative.as_posix()}"
            ) from error
        if stat.S_ISLNK(metadata.st_mode):
            raise RepositoryPathError(
                f"repository path crosses a symlink: {relative.as_posix()}"
            )
        if not stat.S_ISDIR(metadata.st_mode):
            raise RepositoryPathError(
                f"repository path has a non-directory parent: {relative.as_posix()}"
            )
    path = root / relative
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return None
        raise RepositoryPathError(
            f"repository path is missing: {relative.as_posix()}"
        ) from None
    except OSError as error:
        raise RepositoryPathError(
            f"unable to inspect repository path: {relative.as_posix()}"
        ) from error
    if stat.S_ISLNK(metadata.st_mode):
        raise RepositoryPathError(
            f"repository path is a symlink: {relative.as_posix()}"
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise RepositoryPathError(
            f"repository path is not a regular file: {relative.as_posix()}"
        )
    return path
