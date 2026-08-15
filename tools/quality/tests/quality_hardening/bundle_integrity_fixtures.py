from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

BUNDLE_ROOT = "flare-dependencies-fixture-linux-amd64-test"

_RESTORE_ENTRYPOINT = b"""#!/usr/bin/bash
set -Eeuo pipefail
exit 0
"""

_CONTRACT_FILES: dict[str, bytes] = {
    "README.md": b"# Fixture dependency bundle\n",
    "postconditions.tsv": b"# kind\tname\texpected\n",
    "profile-toolchain.tsv": b"# tool\tversion\n",
    "profile.env": b"PROFILE=fixture\n",
    "restore.sh": _RESTORE_ENTRYPOINT,
}


@dataclass(frozen=True, slots=True)
class ArchiveMember:
    name: str
    kind: str = "file"
    data: bytes = b"fixture\n"
    linkname: str = ""
    uid: int = 0
    gid: int = 0
    mode: int | None = None
    pax_headers: Mapping[str, str] | None = None


def file_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def regular_bundle_files(
    payload: Mapping[str, bytes] | None = None,
) -> dict[str, bytes]:
    files = dict(_CONTRACT_FILES)
    files.update(payload or {"payload.txt": b"flat payload\n"})
    return files


def checksum_record(digest: str, relative: str, separator: str = "  ") -> str:
    return f"{digest}{separator}{relative}"


def canonical_manifest(files: Mapping[str, bytes]) -> str:
    return "".join(
        f"{file_digest(content)}  ./{relative}\n"
        for relative, content in sorted(files.items())
    )


def _tar_info(member: ArchiveMember) -> tarfile.TarInfo:
    info = tarfile.TarInfo(member.name)
    info.uid = member.uid
    info.gid = member.gid
    info.uname = "root"
    info.gname = "root"
    info.mtime = 0
    info.pax_headers = dict(member.pax_headers or {})
    if member.kind == "directory":
        info.type = tarfile.DIRTYPE
        info.mode = 0o755 if member.mode is None else member.mode
    elif member.kind == "file":
        info.type = tarfile.REGTYPE
        info.mode = 0o644 if member.mode is None else member.mode
        info.size = len(member.data)
    elif member.kind == "symlink":
        info.type = tarfile.SYMTYPE
        info.mode = 0o777
        info.linkname = member.linkname
    elif member.kind == "hardlink":
        info.type = tarfile.LNKTYPE
        info.mode = 0o644
        info.linkname = member.linkname
    elif member.kind == "fifo":
        info.type = tarfile.FIFOTYPE
        info.mode = 0o644
    else:
        raise ValueError(f"unsupported fixture member kind: {member.kind}")
    return info


def _add_member(archive: tarfile.TarFile, member: ArchiveMember) -> None:
    info = _tar_info(member)
    stream = io.BytesIO(member.data) if member.kind == "file" else None
    archive.addfile(info, stream)


def _manifest_content(
    files: Mapping[str, bytes],
    text: str | None,
    content: bytes | None,
) -> bytes:
    if text is not None and content is not None:
        raise ValueError("manifest_text and manifest_bytes are mutually exclusive")
    if content is not None:
        return content
    if text is not None:
        return text.encode()
    return canonical_manifest(files).encode()


def write_bundle(
    directory: Path,
    *,
    regular_files: Mapping[str, bytes] | None = None,
    manifest_text: str | None = None,
    manifest_bytes: bytes | None = None,
    regular_modes: Mapping[str, int] | None = None,
    extra_members: Sequence[ArchiveMember] = (),
    pax_headers: Mapping[str, str] | None = None,
    archive_format: int = tarfile.GNU_FORMAT,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    files = regular_bundle_files() if regular_files is None else dict(regular_files)
    modes = {"restore.sh": 0o755, **(regular_modes or {})}
    manifest = _manifest_content(files, manifest_text, manifest_bytes)
    archive_path = directory / "fixture-bundle.tar.gz"
    with tarfile.open(
        archive_path,
        "w:gz",
        format=archive_format,
        pax_headers=pax_headers,
    ) as archive:
        _add_member(
            archive,
            ArchiveMember(BUNDLE_ROOT, kind="directory", data=b""),
        )
        for relative, content in sorted(files.items()):
            _add_member(
                archive,
                ArchiveMember(
                    f"{BUNDLE_ROOT}/{relative}",
                    data=content,
                    mode=modes.get(relative),
                ),
            )
        _add_member(
            archive,
            ArchiveMember(
                f"{BUNDLE_ROOT}/SHA256SUMS",
                data=manifest,
            ),
        )
        for member in extra_members:
            _add_member(archive, member)

    write_detached_checksum(archive_path)
    return archive_path


def restore_marker_script(marker: str) -> bytes:
    return f"""#!/usr/bin/bash
set -Eeuo pipefail
IFS=$'\\n\\t'
repo="${{1:?missing target repository}}"
activation="$repo/.flare/profiles/fixture/current/activate.sh"
mkdir -p "$(dirname "$activation")"
printf '#!/usr/bin/bash\\n' > "$activation"
printf '%s\\n' '{marker}' > "$repo/restore-marker"
""".encode()


def write_archive_swap_shim(path: Path) -> Path:
    path.write_text(
        """#!/usr/bin/bash
set -uo pipefail
"$REAL_BUNDLE_PYTHON" "$@"
status=$?
if [[ "$status" -eq 0 ]]; then
  cp -- "$REPLACEMENT_ARCHIVE" "$ORIGINAL_ARCHIVE"
fi
exit "$status"
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def run_restore_wrapper(
    wrapper: Path,
    archive: Path,
    target: Path,
    bundle_python: Path,
    *,
    real_python: Path | None = None,
    replacement: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["FLARE_BUNDLE_PYTHON"] = str(bundle_python)
    if real_python is not None:
        environment["REAL_BUNDLE_PYTHON"] = str(real_python)
    if replacement is not None:
        environment["REPLACEMENT_ARCHIVE"] = str(replacement)
        environment["ORIGINAL_ARCHIVE"] = str(archive)
    return subprocess.run(
        (str(wrapper), str(archive), str(target)),
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=30,
    )


def write_detached_checksum(
    archive_path: Path,
    *,
    digest: str | None = None,
    name: str | None = None,
    separator: str = "  ",
    suffix: str = "\n",
) -> None:
    actual_digest = (
        hashlib.sha256(archive_path.read_bytes()).hexdigest()
        if digest is None
        else digest
    )
    actual_name = archive_path.name if name is None else name
    archive_path.with_name(archive_path.name + ".sha256").write_text(
        f"{actual_digest}{separator}{actual_name}{suffix}",
        encoding="utf-8",
    )
