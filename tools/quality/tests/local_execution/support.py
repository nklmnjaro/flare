import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.local_execution.profile import HostProfile, load_profile

REPO_ROOT = Path(__file__).resolve().parents[4]
PROFILE_SOURCE = REPO_ROOT / "tools/local_execution/host_profile.toml"


@dataclass(frozen=True, slots=True)
class LocalExecutionFixture:
    root: Path
    profile: HostProfile
    uv: Path
    managed_python: Path


def _copy_source(root: Path) -> None:
    for relative in (
        ".python-version",
        "Makefile",
        "flare",
        "pyproject.toml",
        "uv.lock",
    ):
        source = REPO_ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copytree(
        REPO_ROOT / "tools/local_execution",
        root / "tools/local_execution",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    policy = root / "tools/quality/check_repo_policy.py"
    policy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "tools/quality/check_repo_policy.py", policy)


def _managed_python(root: Path) -> Path:
    target = root / ".flare/local-execution/python/cpython/bin/python3.14"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "#!/bin/sh\nexec " + shlex.quote(sys.executable) + ' "$@"\n',
        encoding="utf-8",
    )
    target.chmod(0o755)
    return target


def write_fake_uv(
    root: Path,
    *,
    name: str = "uv",
    version: str = "0.12.3",
    sync_exit: int = 0,
    sync_error: str = "",
) -> Path:
    target = root / "host-bin" / name
    source_site = next(
        Path(entry) for entry in sys.path if entry.endswith("site-packages")
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        f"VERSION={version!r}\n"
        f"SYNC_EXIT={sync_exit}\n"
        f"SYNC_ERROR={sync_error!r}\n"
        'case "${1:-}" in\n'
        "  --version) printf 'uv %s (fixture)\\n' \"$VERSION\" ;;\n"
        "  sync)\n"
        '    if [ "$SYNC_EXIT" -ne 0 ]; then printf \'%s\\n\' "$SYNC_ERROR" >&2; exit "$SYNC_EXIT"; fi\n'
        '    "$4" -m venv --without-pip "$UV_PROJECT_ENVIRONMENT"\n'
        '    CANDIDATE_SITE=$("$UV_PROJECT_ENVIRONMENT/bin/python" -c '
        "'import site; print(site.getsitepackages()[0])')\n"
        f"    printf '%s\\n' {shlex.quote(str(source_site))} > "
        '"$CANDIDATE_SITE/flare-fixture.pth"\n'
        "    ;;\n"
        "  *) printf 'unsupported fake uv operation\\n' >&2; exit 64 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    target.chmod(0o755)
    return target


def create_fixture(root: Path) -> LocalExecutionFixture:
    root.mkdir(parents=True)
    _copy_source(root)
    profile = load_profile(root / "tools/local_execution/host_profile.toml")
    return LocalExecutionFixture(
        root=root,
        profile=profile,
        uv=write_fake_uv(root),
        managed_python=_managed_python(root),
    )


def source_snapshot(root: Path) -> tuple[tuple[str, bytes], ...]:
    excluded = {".cache", ".flare", ".venv", "__pycache__"}
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not any(part in excluded for part in path.relative_to(root).parts)
    )


def complete_snapshot(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    )
