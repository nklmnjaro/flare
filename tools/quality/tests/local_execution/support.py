import base64
import hashlib
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.local_execution.profile import HostProfile, load_profile

REPO_ROOT = Path(__file__).resolve().parents[4]
PROFILE_SOURCE = REPO_ROOT / "tools/local_execution/host_profile.toml"
UV_VERSION_BARRIER_SCRIPT = (
    '    if [ -f "$FIXTURE_ROOT/enable-version-barrier" ]; then\n'
    '      barrier="$FIXTURE_ROOT/uv-version-barrier"\n'
    '      /usr/bin/mkdir -p "$barrier"\n'
    '      : > "$barrier/$$"\n'
    "      attempts=0\n"
    "      while :; do\n"
    "        participants=0\n"
    '        for participant in "$barrier"/*; do\n'
    '          [ -f "$participant" ] && participants=$((participants + 1))\n'
    "        done\n"
    '        [ "$participants" -ge 2 ] && break\n'
    "        attempts=$((attempts + 1))\n"
    '        [ "$attempts" -lt 500 ] || exit 73\n'
    "        /usr/bin/sleep 0.01\n"
    "      done\n"
    "    fi\n"
)
UV_INSTALL_GUARD_SCRIPT = (
    '        if [ -f "$FIXTURE_ROOT/enable-install-guard" ]; then\n'
    '          guard="$FIXTURE_ROOT/uv-install-active"\n'
    '          if ! /usr/bin/mkdir "$guard" '
    "2>/dev/null; then\n"
    '            : > "$FIXTURE_ROOT/uv-install-overlap"\n'
    "            exit 74\n"
    "          fi\n"
    "          trap '/usr/bin/rm -rf -- \"$guard\"' "
    "EXIT HUP INT TERM\n"
    '          : > "$FIXTURE_ROOT/uv-install-observed"\n'
    "          /usr/bin/sleep 0.2\n"
    "        fi\n"
)
UV_INSTALL_WAIT_SCRIPT = (
    '        if [ -f "$FIXTURE_ROOT/enable-install-wait" ]; then\n'
    '          : > "$FIXTURE_ROOT/uv-install-started"\n'
    "          attempts=0\n"
    '          while [ ! -f "$FIXTURE_ROOT/uv-install-release" ]; do\n'
    "            attempts=$((attempts + 1))\n"
    '            [ "$attempts" -lt 500 ] || exit 75\n'
    "            /usr/bin/sleep 0.01\n"
    "          done\n"
    "        fi\n"
)
UV_SYNC_SCRIPT = (
    '    if [ "$SYNC_EXIT" -ne 0 ]; then '
    'printf \'%s\\n\' "$SYNC_ERROR" >&2; exit "$SYNC_EXIT"; fi\n'
    '    "$4" -B -m venv --without-pip --copies "$UV_PROJECT_ENVIRONMENT"\n'
    '    printf "#!%s/bin/python\\nprint(\\"body-only:%s\\")\\n" '
    '"$UV_PROJECT_ENVIRONMENT" "$UV_PROJECT_ENVIRONMENT" '
    '> "$UV_PROJECT_ENVIRONMENT/bin/fixture-tool"\n'
    '    /usr/bin/chmod 755 "$UV_PROJECT_ENVIRONMENT/bin/fixture-tool"\n'
    '    "$4" -I -B -S -c \'import base64,pathlib,re,tomllib\n'
    "root=pathlib.Path.cwd()\n"
    'value=tomllib.loads((root/"pyproject.toml").read_text())\n'
    'entries=(*value["project"]["dependencies"],'
    '*value["dependency-groups"]["dev"])\n'
    'site=pathlib.Path(__import__("os").environ["UV_PROJECT_ENVIRONMENT"])/'
    '"lib/python3.14/site-packages"\n'
    "site.mkdir(parents=True,exist_ok=True)\n"
    "for entry in entries:\n"
    ' name,version=entry.split("==",1)\n'
    ' normalized=re.sub(r"[-_.]+","_",name)\n'
    ' metadata=site/f"{normalized}-{version}.dist-info"\n'
    " metadata.mkdir()\n"
    ' (metadata/"METADATA").write_text('
    'f"Metadata-Version: 2.4\\nName: {name}\\nVersion: {version}\\n")\n'
)


@dataclass(frozen=True, slots=True)
class LocalExecutionFixture:
    root: Path
    profile: HostProfile
    uv: Path
    managed_python: Path


def _copy_source(root: Path) -> None:
    for relative in (
        ".gitlint",
        ".pre-commit-config.yaml",
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
    shutil.copytree(
        REPO_ROOT / "tools/platform/dependency_bundles",
        root / "tools/platform/dependency_bundles",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    policy = root / "tools/quality/check_repo_policy.py"
    policy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "tools/quality/check_repo_policy.py", policy)


def _managed_python_path(root: Path) -> Path:
    profile = load_profile(root / "tools/local_execution/host_profile.toml")
    minor = profile.python_version.rsplit(".", maxsplit=1)[0]
    installation = (
        f"{profile.python_implementation}-{profile.python_version}-"
        f"{profile.os.lower()}-{profile.architecture}-gnu"
    )
    return (
        profile.path(root, profile.python_install_dir)
        / installation
        / "bin"
        / f"python{minor}"
    )


def _managed_python(root: Path) -> Path:
    target = _managed_python_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_managed_payload(root), encoding="utf-8")
    target.chmod(0o755)
    return target


def _managed_payload(root: Path) -> str:
    trigger = root / ".flare/local-execution/python/execute-canary"
    marker = root / "managed-python-executed"
    return (
        "#!/bin/sh\n"
        f"if [ -f {shlex.quote(str(trigger))} ]; then "
        f": > {shlex.quote(str(marker))}; fi\n"
        'case "$0" in\n'
        "  */bin/python|*/bin/python3|*/bin/python3.14|*/bin/𝜋thon)\n"
        "    environment=${0%/bin/*}\n"
        '    site="$environment/lib/python3.14/site-packages/sitecustomize.py"\n'
        f'    [ ! -f "$site" ] || {shlex.quote(sys.executable)} -I -B -S "$site"\n'
        "    ;;\n"
        "esac\n"
        "exec " + shlex.quote(sys.executable) + ' -B "$@"\n'
    )


def _publish_fixture_stage0_state(root: Path) -> None:
    flare_root = root / ".flare"
    state = root / ".flare/local-execution"
    state.mkdir(parents=True, exist_ok=True)
    for directory in (flare_root, state):
        directory.chmod(0o700)
    lock = state / "stage0-bootstrap.lock"
    lock.write_text("flare-stage0-bootstrap-lock-v1\n", encoding="ascii")
    lock.chmod(0o600)
    managed_root = state / "python"
    for path in (managed_root, *managed_root.rglob("*")):
        if not path.is_symlink():
            path.chmod(path.stat().st_mode & ~0o022)
    managed_root.chmod(0o700)
    completed = subprocess.run(
        (
            "/usr/bin/tar",
            "--sort=name",
            "--format=posix",
            "--one-file-system",
            "--mtime=UTC 1970-01-01",
            "--owner=0",
            "--group=0",
            "--numeric-owner",
            "--pax-option=delete=atime,delete=ctime",
            "-C",
            str(managed_root),
            "-cf",
            "-",
            ".",
        ),
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        check=True,
    )
    seal = state / "stage0-python.sha256"
    seal.write_text(
        hashlib.sha256(completed.stdout).hexdigest() + "\n", encoding="ascii"
    )
    seal.chmod(0o600)


def write_fake_uv(
    root: Path,
    *,
    name: str = "uv",
    version: str = "0.12.3",
    sync_exit: int = 0,
    sync_error: str = "",
) -> Path:
    target = root / "host-bin" / name
    managed_python = _managed_python_path(root)
    managed_payload = _managed_payload(root)
    probe = root / "stage1-environment-probe.json"
    probe_source = (
        "import json, os, pathlib, sys\n"
        f"path = pathlib.Path({str(probe)!r})\n"
        "names = ('PIP_EXTRA_INDEX_URL','PIP_INDEX_URL','PYTEST_ADDOPTS',"
        "'PYTHONPATH','UV_EXTRA_INDEX_URL','UV_INDEX_URL','UV_KEYRING_PROVIDER')\n"
        "value = {'optimize': sys.flags.optimize, "
        "'sensitive': sorted(name for name in names if name in os.environ)}\n"
        "path.write_text(json.dumps(value, sort_keys=True), encoding='utf-8')\n"
    )
    probe_encoded = base64.b64encode(probe_source.encode()).decode("ascii")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        f"VERSION={version!r}\n"
        f"SYNC_EXIT={sync_exit}\n"
        f"SYNC_ERROR={sync_error!r}\n"
        f"FIXTURE_ROOT={shlex.quote(str(root))}\n"
        + 'if [ "${1:-}" = "--no-config" ]; then\n'
        "  shift\n"
        'elif [ "${1:-}" != "--version" ]; then\n'
        '  : > "$FIXTURE_ROOT/uv-config-bypass"\n'
        "  exit 76\n"
        "fi\n"
        'case "${1:-}" in\n'
        "  --version)\n"
        + UV_VERSION_BARRIER_SCRIPT
        + "    printf 'uv %s (fixture)\\n' \"$VERSION\"\n"
        "    ;;\n"
        "  python)\n"
        '    case "${2:-}" in\n'
        "      install)\n"
        + UV_INSTALL_GUARD_SCRIPT
        + UV_INSTALL_WAIT_SCRIPT
        + f"        /usr/bin/rm -rf -- {shlex.quote(str(managed_python.parents[1]))}\n"
        + f"        /usr/bin/mkdir -p {shlex.quote(str(managed_python.parent))}\n"
        + f"        printf '%s' {shlex.quote(managed_payload)} > "
        f"{shlex.quote(str(managed_python))}\n"
        f"        /usr/bin/chmod 755 {shlex.quote(str(managed_python))}\n"
        "        ;;\n"
        f"      find) printf '%s\\n' {shlex.quote(str(managed_python))} ;;\n"
        "      *) printf 'unsupported fake uv python operation\\n' >&2; exit 64 ;;\n"
        "    esac\n"
        "    ;;\n"
        "  sync)\n" + UV_SYNC_SCRIPT + f'(site/"sitecustomize.py").write_bytes('
        f'base64.b64decode("{probe_encoded}"))\'\n'
        "    for alias in python python3 python3.14 𝜋thon; do\n"
        '      /usr/bin/rm -f -- "$UV_PROJECT_ENVIRONMENT/bin/$alias"\n'
        '      /usr/bin/ln -s "$4" "$UV_PROJECT_ENVIRONMENT/bin/$alias"\n'
        "    done\n"
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
    fixture = LocalExecutionFixture(
        root=root,
        profile=profile,
        uv=write_fake_uv(root),
        managed_python=_managed_python(root),
    )
    _publish_fixture_stage0_state(root)
    return fixture


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
