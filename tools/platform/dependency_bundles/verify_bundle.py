from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import posixpath
import stat
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, NoReturn, Protocol

sys.dont_write_bytecode = True

_DIGEST_LENGTH = 64
_CHECKSUM_SEPARATOR = "  "
MAX_ARCHIVE_BYTES = 300 * 1024 * 1024
MAX_CHECKSUM_BYTES = 4 * 1024
MAX_ARCHIVE_MEMBERS = 100_000
MAX_ARCHIVE_MEMBER_PATH_BYTES = 4 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_EXTRACTED_BYTES = 4 * 1024 * 1024 * 1024
MAX_INTERNAL_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_TAR_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_RAW_HEADERS = 300_000
MAX_ARCHIVE_EXTENSION_BYTES = 64 * 1024
MAX_ARCHIVE_EXTENSION_TOTAL_BYTES = 32 * 1024 * 1024
MAX_CONSECUTIVE_EXTENSION_HEADERS = 4
_TAR_BLOCK_BYTES = 512
_GNU_EXTENSION_TYPES = frozenset(
    {
        tarfile.GNUTYPE_LONGNAME,
        tarfile.GNUTYPE_LONGLINK,
    }
)
_PAX_EXTENSION_TYPES = frozenset(
    {
        tarfile.XHDTYPE,
        tarfile.XGLTYPE,
        tarfile.SOLARIS_XHDTYPE,
    }
)
_TAR_EXTENSION_TYPES = _GNU_EXTENSION_TYPES | _PAX_EXTENSION_TYPES


class _BinaryReader(Protocol):
    def read(self, size: int = -1) -> bytes: ...


def fail(message: str) -> NoReturn:
    raise AssertionError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def _opened_regular(path: Path, label: str) -> Iterator[BinaryIO]:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"{label} missing, unsafe or unreadable: {exc.strerror}")
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            fail(f"{label} is not a regular file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            yield stream
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _is_regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _read_utf8(path: Path, label: str, maximum: int) -> str:
    try:
        with path.open("rb") as stream:
            content = stream.read(maximum + 1)
        if len(content) > maximum:
            fail(f"{label} exceeds {maximum} bytes")
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        fail(f"{label} is not UTF-8: byte {exc.start}")


def _decode_utf8(content: bytes, label: str) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        fail(f"{label} is not UTF-8: byte {exc.start}")


def _has_ambiguous_path_text(value: str) -> bool:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return True
    return (
        "\\" in value
        or unicodedata.normalize("NFC", value) != value
        or any(unicodedata.category(character).startswith("C") for character in value)
    )


def _checksum_record(line: str, label: str) -> tuple[str, str]:
    digest = line[:_DIGEST_LENGTH]
    if len(digest) != _DIGEST_LENGTH or any(
        character not in "0123456789abcdef" for character in digest
    ):
        fail(f"{label} digest must be 64 lowercase hexadecimal characters")
    if line[_DIGEST_LENGTH : _DIGEST_LENGTH + 2] != _CHECKSUM_SEPARATOR:
        fail(f"{label} must use exactly two spaces after the digest")
    target = line[_DIGEST_LENGTH + 2 :]
    if not target:
        fail(f"{label} target path is empty")
    return digest, target


def _single_checksum_record(text: str, label: str) -> tuple[str, str]:
    text = text.removesuffix("\n")
    if not text or "\n" in text or "\r" in text:
        fail(f"{label} must contain exactly one checksum record")
    digest, target = _checksum_record(text, label)
    if _has_ambiguous_path_text(target):
        fail(f"{label} target contains ambiguous path text")
    return digest, target


def _snapshot_verified_archive(path: Path, directory: Path) -> Path:
    checksum_path = path.with_name(path.name + ".sha256")
    snapshot = directory / "archive.snapshot"
    with (
        _opened_regular(path, "archive") as archive_stream,
        _opened_regular(checksum_path, "detached .sha256") as checksum_stream,
        snapshot.open("xb") as snapshot_stream,
    ):
        archive_bytes = os.fstat(archive_stream.fileno()).st_size
        if archive_bytes > MAX_ARCHIVE_BYTES:
            fail(f"archive exceeds {MAX_ARCHIVE_BYTES} bytes")
        checksum_bytes = checksum_stream.read(MAX_CHECKSUM_BYTES + 1)
        if len(checksum_bytes) > MAX_CHECKSUM_BYTES:
            fail(f"detached checksum exceeds {MAX_CHECKSUM_BYTES} bytes")
        digest, name = _single_checksum_record(
            _decode_utf8(checksum_bytes, "detached checksum"),
            "detached checksum",
        )
        if posixpath.basename(name) != name or name in {".", ".."}:
            fail("detached checksum contains a path")
        if name != path.name:
            fail("detached checksum basename mismatch")

        observed = hashlib.sha256()
        copied = 0
        for chunk in iter(lambda: archive_stream.read(1024 * 1024), b""):
            copied += len(chunk)
            if copied > MAX_ARCHIVE_BYTES:
                fail(f"archive exceeds {MAX_ARCHIVE_BYTES} bytes")
            observed.update(chunk)
            snapshot_stream.write(chunk)
    if observed.hexdigest() != digest:
        fail("detached checksum mismatch")
    return snapshot


def _shared_canonical_path(value: str, label: str) -> str:
    repository_root = Path(__file__).resolve().parents[3]
    repository_root_text = str(repository_root)
    if repository_root_text not in sys.path:
        sys.path.insert(0, repository_root_text)
    from tools.canonical_paths import canonical_relative_posix_path

    try:
        return canonical_relative_posix_path(value, label=label)
    except ValueError as exc:
        fail(str(exc))


def _canonical_archive_name(name: str) -> str:
    return _shared_canonical_path(name, "archive member path")


def _inside_archive_root(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _verify_link(member: tarfile.TarInfo, root: str) -> None:
    target = member.linkname
    kind = "symlink" if member.issym() else "hardlink"
    if not target:
        fail(f"empty {kind} target: {member.name}")
    if _has_ambiguous_path_text(target):
        fail(f"ambiguous {kind} target: {member.name} -> {target!r}")
    if member.issym():
        if posixpath.isabs(target):
            fail(f"absolute {kind}: {member.name} -> {target}")
        resolved = posixpath.normpath(
            posixpath.join(posixpath.dirname(member.name), target)
        )
    else:
        resolved = _shared_canonical_path(target, "hardlink target")
    if not _inside_archive_root(resolved, root):
        fail(f"escaping {kind}: {member.name} -> {target}")


def _archive_root(members: list[tarfile.TarInfo]) -> str:
    if not members:
        fail("archive has no members")
    seen_exact: set[str] = set()
    seen_canonical: dict[str, str] = {}
    roots: set[str] = set()
    for member in members:
        if member.name in seen_exact:
            fail(f"duplicate archive member: {member.name}")
        seen_exact.add(member.name)

        canonical_candidate = posixpath.normpath(member.name)
        previous = seen_canonical.get(canonical_candidate)
        if previous is not None:
            fail(
                f"canonical duplicate archive members: {previous!r} and {member.name!r}"
            )
        seen_canonical[canonical_candidate] = member.name

        canonical = _canonical_archive_name(member.name)
        roots.add(canonical.split("/", 1)[0])
        if not (member.isdir() or member.isreg() or member.issym() or member.islnk()):
            fail(f"unsupported archive member type: {member.name}")
        if member.uid != 0 or member.gid != 0:
            fail(
                f"non-normalized numeric owner metadata: {member.name}: "
                f"{member.uid}:{member.gid}"
            )
        if member.uname not in {"", "root"} or member.gname not in {"", "root"}:
            fail(
                f"non-normalized owner metadata: {member.name}: "
                f"{member.uname}:{member.gname}"
            )
        if "/home/" in f"/{canonical}" or "/Users/" in f"/{canonical}":
            fail(f"local workstation path leaked: {member.name}")

    if len(roots) != 1:
        fail(f"archive must have one top-level root: {sorted(roots)}")
    root = next(iter(roots))
    members_by_name = {member.name: member for member in members}
    for member in members:
        parent = posixpath.dirname(member.name)
        while parent:
            ancestor = members_by_name.get(parent)
            if ancestor is not None and ancestor.issym():
                fail(f"archive member descends through a symlink: {member.name}")
            if ancestor is not None and not ancestor.isdir():
                fail(f"archive member descends through a non-directory: {member.name}")
            parent = posixpath.dirname(parent)
        if member.issym() or member.islnk():
            _verify_link(member, root)
        if member.islnk():
            target = member.linkname
            target_member = members_by_name.get(target)
            if target_member is None or not target_member.isreg():
                fail(f"hardlink target is not a regular archive member: {member.name}")
    return root


def _bounded_archive_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    extracted_bytes = 0
    for member in archive:
        if len(members) >= MAX_ARCHIVE_MEMBERS:
            fail(f"archive exceeds {MAX_ARCHIVE_MEMBERS} members")
        name_bytes = len(member.name.encode("utf-8", errors="surrogatepass"))
        link_bytes = len(member.linkname.encode("utf-8", errors="surrogatepass"))
        if max(name_bytes, link_bytes) > MAX_ARCHIVE_MEMBER_PATH_BYTES:
            fail(
                "archive member path or link target exceeds "
                f"{MAX_ARCHIVE_MEMBER_PATH_BYTES} bytes"
            )
        if member.size < 0 or member.size > MAX_ARCHIVE_MEMBER_BYTES:
            fail(f"archive member exceeds {MAX_ARCHIVE_MEMBER_BYTES} bytes")
        if member.isreg():
            extracted_bytes += member.size
            if extracted_bytes > MAX_ARCHIVE_EXTRACTED_BYTES:
                fail(
                    "archive regular payload exceeds "
                    f"{MAX_ARCHIVE_EXTRACTED_BYTES} bytes"
                )
        members.append(member)
    return members


def _discard_exact(stream: _BinaryReader, size: int) -> None:
    remaining = size
    while remaining:
        chunk = stream.read(min(1024 * 1024, remaining))
        if not chunk:
            fail("compressed archive has a truncated member body")
        remaining -= len(chunk)


def _preflight_tar_stream(snapshot: Path) -> None:
    consumed = 0
    headers = 0
    extension_bytes = 0
    consecutive_extensions = 0
    with gzip.open(snapshot, "rb") as stream:
        while True:
            header = stream.read(_TAR_BLOCK_BYTES)
            if not header:
                return
            if len(header) != _TAR_BLOCK_BYTES:
                fail("compressed archive has a truncated tar header")
            consumed += _TAR_BLOCK_BYTES
            if consumed > MAX_ARCHIVE_TAR_BYTES:
                fail(f"uncompressed tar exceeds {MAX_ARCHIVE_TAR_BYTES} bytes")
            if header == bytes(_TAR_BLOCK_BYTES):
                return
            headers += 1
            if headers > MAX_ARCHIVE_RAW_HEADERS:
                fail(f"archive exceeds {MAX_ARCHIVE_RAW_HEADERS} raw tar headers")
            try:
                member = tarfile.TarInfo.frombuf(
                    header,
                    encoding="utf-8",
                    errors="surrogateescape",
                )
            except tarfile.HeaderError as error:
                fail(f"invalid raw tar header: {error}")
            if member.type == tarfile.GNUTYPE_SPARSE:
                fail("GNU sparse archive members are unsupported")
            if member.size < 0 or member.size > MAX_ARCHIVE_MEMBER_BYTES:
                fail(f"archive member exceeds {MAX_ARCHIVE_MEMBER_BYTES} bytes")
            if member.type in _TAR_EXTENSION_TYPES:
                consecutive_extensions += 1
                if consecutive_extensions > MAX_CONSECUTIVE_EXTENSION_HEADERS:
                    fail(
                        "archive exceeds "
                        f"{MAX_CONSECUTIVE_EXTENSION_HEADERS} consecutive "
                        "extension headers"
                    )
                if member.type in _PAX_EXTENSION_TYPES:
                    fail("PAX archive headers are unsupported")
                if member.size > MAX_ARCHIVE_EXTENSION_BYTES:
                    fail(
                        "archive extension header exceeds "
                        f"{MAX_ARCHIVE_EXTENSION_BYTES} bytes"
                    )
                extension_bytes += member.size
                if extension_bytes > MAX_ARCHIVE_EXTENSION_TOTAL_BYTES:
                    fail(
                        "archive extension metadata exceeds "
                        f"{MAX_ARCHIVE_EXTENSION_TOTAL_BYTES} bytes"
                    )
            else:
                consecutive_extensions = 0
            body_bytes = (
                (member.size + _TAR_BLOCK_BYTES - 1) // _TAR_BLOCK_BYTES
            ) * _TAR_BLOCK_BYTES
            if consumed + body_bytes > MAX_ARCHIVE_TAR_BYTES:
                fail(f"uncompressed tar exceeds {MAX_ARCHIVE_TAR_BYTES} bytes")
            _discard_exact(stream, body_bytes)
            consumed += body_bytes


def _verify_pre_extraction_contract(members: list[tarfile.TarInfo], root: str) -> None:
    manifest_name = f"{root}/SHA256SUMS"
    manifest = next((item for item in members if item.name == manifest_name), None)
    if manifest is None or not manifest.isreg():
        fail("SHA256SUMS is missing or not a regular file")
    if manifest.size > MAX_INTERNAL_MANIFEST_BYTES:
        fail(f"internal checksum manifest exceeds {MAX_INTERNAL_MANIFEST_BYTES} bytes")


def _canonical_manifest_path(relative: str) -> str:
    if posixpath.isabs(relative):
        fail(f"internal checksum target is absolute: {relative}")
    if not relative.startswith("./"):
        fail(f"internal checksum target lacks canonical ./ prefix: {relative}")
    payload_path = relative[2:]
    return _shared_canonical_path(payload_path, "internal checksum target")


def _manifest_records(manifest: Path) -> tuple[tuple[str, str], ...]:
    text = _read_utf8(
        manifest,
        "internal checksum manifest",
        MAX_INTERNAL_MANIFEST_BYTES,
    )
    text = text.removesuffix("\n")
    if not text:
        fail("internal checksum manifest is empty")
    if "\r" in text:
        fail("internal checksum manifest contains a control character")

    records: list[tuple[str, str]] = []
    seen_exact: set[str] = set()
    seen_canonical: dict[str, str] = {}
    for line_number, line in enumerate(text.split("\n"), start=1):
        if not line:
            fail(f"internal checksum manifest has a blank line at {line_number}")
        expected, relative = _checksum_record(
            line,
            f"internal checksum record {line_number}",
        )
        if relative in seen_exact:
            fail(f"duplicate internal checksum target: {relative}")
        seen_exact.add(relative)

        candidate = relative.removeprefix("./")
        canonical_candidate = posixpath.normpath(candidate)
        previous = seen_canonical.get(canonical_candidate)
        if previous is not None:
            fail(
                "canonical duplicate internal checksum targets: "
                f"{previous!r} and {relative!r}"
            )
        canonical = _canonical_manifest_path(relative)
        seen_canonical[canonical] = relative
        if canonical == "SHA256SUMS":
            fail("SHA256SUMS must not hash itself")
        records.append((expected, canonical))
    return tuple(records)


def _regular_payload_paths(extracted: Path) -> set[str]:
    regular: set[str] = set()
    for directory, directory_names, file_names in os.walk(
        extracted,
        topdown=True,
        followlinks=False,
    ):
        directory_path = Path(directory)
        directory_names[:] = [
            name
            for name in directory_names
            if stat.S_ISDIR((directory_path / name).lstat().st_mode)
        ]
        for name in file_names:
            path = directory_path / name
            if _is_regular_file(path):
                relative = path.relative_to(extracted).as_posix()
                if relative != "SHA256SUMS":
                    regular.add(relative)
    return regular


def _resolve_manifest_target(target: Path, root: Path, relative: str) -> Path:
    try:
        resolved = target.resolve(strict=False)
    except OSError:
        fail(f"internal checksum target cannot be resolved: ./{relative}")
    except RuntimeError:
        fail(f"internal checksum target cannot be resolved: ./{relative}")
    if not resolved.is_relative_to(root):
        fail(f"internal checksum target escapes extraction root: ./{relative}")
    return resolved


def _verify_internal_checksums(extracted: Path) -> None:
    manifest = extracted / "SHA256SUMS"
    if not _is_regular_file(manifest):
        fail("SHA256SUMS is missing or not a regular file")
    records = _manifest_records(manifest)
    declared = {relative for _, relative in records}
    payload = _regular_payload_paths(extracted)

    unlisted = sorted(payload - declared)
    if unlisted:
        fail(f"unlisted regular payload file: {unlisted[0]}")
    undeclared = sorted(declared - payload)
    if undeclared:
        relative = undeclared[0]
        target = extracted / relative
        root = extracted.resolve()
        _resolve_manifest_target(target, root, relative)
        if target.exists() or target.is_symlink():
            fail(f"internal checksum target is not a regular file: ./{relative}")
        fail(f"internal checksum target missing: ./{relative}")

    root = extracted.resolve()
    for expected, relative in records:
        target = extracted / relative
        _resolve_manifest_target(target, root, relative)
        if not _is_regular_file(target):
            fail(f"internal checksum target is not a regular file: ./{relative}")
        if sha256(target) != expected:
            fail(f"internal checksum mismatch: ./{relative}")


def _verify_restore_entrypoint(extracted: Path) -> None:
    restore = extracted / "restore.sh"
    if restore.stat().st_mode & 0o111 == 0:
        fail("restore.sh is not executable")
    result = subprocess.run(
        ["/usr/bin/bash", "-n", str(restore)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        fail(f"restore.sh syntax error: {result.stderr}")


def _verify_extracted(extracted: Path) -> None:
    required_names = (
        "SHA256SUMS",
        "restore.sh",
        "README.md",
        "profile.env",
        "profile-toolchain.tsv",
        "postconditions.tsv",
    )
    for name in required_names:
        if not _is_regular_file(extracted / name):
            fail(f"missing or non-regular bundle contract file: {name}")
    _verify_internal_checksums(extracted)
    _verify_restore_entrypoint(extracted)


def _checked_extract_destination(path: Path) -> Path:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        fail(f"extraction destination is unavailable: {exc.strerror}")
    if not stat.S_ISDIR(mode):
        fail("extraction destination is not a regular directory")
    if any(path.iterdir()):
        fail("extraction destination is not empty")
    return path


def _verify_snapshot(snapshot: Path, destination: Path) -> None:
    _preflight_tar_stream(snapshot)
    with tarfile.open(snapshot, "r:gz") as archive:
        members = _bounded_archive_members(archive)
        root = _archive_root(members)
        _verify_pre_extraction_contract(members, root)
        archive.extractall(destination, members=members, filter="data")
        _verify_extracted(destination / root)


def check_archive(path: Path, *, extract_to: Path | None = None) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="flare-bundle-snapshot-") as directory:
        snapshot = _snapshot_verified_archive(path, Path(directory))
        if extract_to is None:
            with tempfile.TemporaryDirectory(
                prefix="flare-bundle-verify-"
            ) as extraction_directory:
                _verify_snapshot(snapshot, Path(extraction_directory))
        else:
            _verify_snapshot(snapshot, _checked_extract_destination(extract_to))

    return [
        "detached checksum bound to one immutable archive snapshot",
        "single canonical top-level archive root",
        "archive members, ownership and links are safe",
        "archive snapshot and extraction resource bounds are enforced",
        "internal manifest is canonical, complete and valid",
        "restore shell syntax valid",
        "restore entrypoint executable mode valid",
        "required bundle contract files are regular",
        "profile manifest and postconditions present",
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extract-to", type=Path)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        findings = check_archive(args.archive, extract_to=args.extract_to)
    except (AssertionError, OSError, tarfile.TarError, ValueError) as exc:
        print(f"BUNDLE CONTRACT FAIL: {exc}", file=sys.stderr)
        return 1
    for finding in findings:
        print(f"PASS: {finding}")
    print("BUNDLE CONTRACT PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
