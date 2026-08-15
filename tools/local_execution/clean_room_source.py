import os
import stat
from pathlib import Path
from typing import NoReturn

ROOT_EXCLUDED_DIRECTORIES = frozenset({".cache", ".flare", ".tmp", ".venv"})
NESTED_EXCLUDED_DIRECTORIES = frozenset(
    {".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
)


def _directory_is_excluded(parts: tuple[str, ...]) -> bool:
    name = parts[-1]
    return name in NESTED_EXCLUDED_DIRECTORIES or (
        len(parts) == 1 and name in ROOT_EXCLUDED_DIRECTORIES
    )


def _raise_walk_error(error: OSError) -> NoReturn:
    raise error


def _is_source_entry(path: Path) -> bool:
    mode = path.lstat().st_mode
    return stat.S_ISREG(mode) or stat.S_ISLNK(mode)


def discover_source_paths(root: Path) -> tuple[str, ...]:
    discovered: list[str] = []
    for current_raw, directories, files in os.walk(
        root,
        topdown=True,
        onerror=_raise_walk_error,
        followlinks=False,
    ):
        current = Path(current_raw)
        relative_directory = current.relative_to(root)
        retained_directories: list[str] = []
        for name in sorted(directories, key=os.fsencode):
            path = current / name
            parts = (*relative_directory.parts, name)
            if _directory_is_excluded(parts):
                continue
            if stat.S_ISLNK(path.lstat().st_mode):
                discovered.append(Path(*parts).as_posix())
            else:
                retained_directories.append(name)
        directories[:] = retained_directories
        for name in sorted(files, key=os.fsencode):
            path = current / name
            if path.suffix == ".pyc" or not _is_source_entry(path):
                continue
            discovered.append((relative_directory / name).as_posix())
    return tuple(sorted(discovered, key=str.encode))
