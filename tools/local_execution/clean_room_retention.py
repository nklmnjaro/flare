import hashlib
import os
import shutil
import stat
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

SOURCE_MANIFEST_NAME = "SOURCE_MANIFEST.json"
PROOF_NAME = "proof.json"
PROOF_TEMP_NAME = ".proof.json.tmp"
EVIDENCE_NAMES = frozenset({SOURCE_MANIFEST_NAME, PROOF_NAME})
CHECKOUT_NAMES = ("checkout-a", "checkout-b")
MAX_EVIDENCE_BYTES = 16_000_000
MAX_DIAGNOSTIC_TEXT = 400
MAX_REMAINING_MEMBERS = 16
MORE_MEMBERS = "<more-members>"
SYMLINK_SAFE_RMTREE = shutil.rmtree.avoids_symlink_attacks


def host_state_name(checkout_name: str) -> str:
    return f"{checkout_name}-host-state"


TRANSIENT_NAMES = frozenset(
    (*CHECKOUT_NAMES, *(host_state_name(name) for name in CHECKOUT_NAMES))
)
INITIAL_NAMES = TRANSIENT_NAMES | {SOURCE_MANIFEST_NAME}


@dataclass(frozen=True, slots=True)
class EvidenceIdentity:
    device: int
    inode: int
    owner: int
    links: int
    mode: int
    size: int
    sha256: str
    ctime_ns: int
    mtime_ns: int


class CleanRoomRetentionError(RuntimeError):
    operation: str
    entry: str
    expected: str
    actual: str
    partial_cleanup_applied: bool
    remaining_members: tuple[str, ...]

    def __init__(
        self,
        operation: str,
        entry: str,
        expected: str,
        actual: str,
        *,
        partial_cleanup_applied: bool,
        remaining_members: tuple[str, ...],
    ) -> None:
        self.operation = operation
        self.entry = entry[:MAX_DIAGNOSTIC_TEXT]
        self.expected = expected[:MAX_DIAGNOSTIC_TEXT]
        self.actual = actual[:MAX_DIAGNOSTIC_TEXT]
        self.partial_cleanup_applied = partial_cleanup_applied
        self.remaining_members = remaining_members
        super().__init__(
            f"operation={operation} entry={self.entry!r} expected={self.expected!r} "
            f"actual={self.actual!r} partial_cleanup_applied="
            f"{partial_cleanup_applied} remaining_members={remaining_members!r}"
        )


def _bounded_member_names(
    descriptor: int,
    limit: int,
) -> tuple[tuple[str, ...], bool]:
    names: list[str] = []
    with os.scandir(descriptor) as entries:
        for entry in entries:
            if len(names) == limit:
                return tuple(sorted(names, key=os.fsencode)), True
            names.append(entry.name[:MAX_DIAGNOSTIC_TEXT])
    return tuple(sorted(names, key=os.fsencode)), False


def _remaining_members(descriptor: int) -> tuple[str, ...]:
    try:
        names, truncated = _bounded_member_names(
            descriptor,
            MAX_REMAINING_MEMBERS,
        )
    except OSError as error:
        return (f"<unavailable:{type(error).__name__}:{error.errno}>",)
    return (*names, MORE_MEMBERS) if truncated else names


def _fail(
    descriptor: int,
    operation: str,
    entry: str,
    expected: str,
    actual: str,
    *,
    partial: bool,
) -> NoReturn:
    raise CleanRoomRetentionError(
        operation,
        entry,
        expected,
        actual,
        partial_cleanup_applied=partial,
        remaining_members=_remaining_members(descriptor),
    )


def _open_run_root(run_root: Path) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        return os.open(run_root, flags)
    except OSError as error:
        raise CleanRoomRetentionError(
            "open-run-root",
            str(run_root),
            "owned 0700 directory opened without following symlinks",
            f"{type(error).__name__}: errno={error.errno}",
            partial_cleanup_applied=False,
            remaining_members=(),
        ) from error


def _require_run_root(descriptor: int) -> os.stat_result:
    try:
        metadata = os.fstat(descriptor)
    except OSError as error:
        _fail(
            descriptor,
            "stat-run-root",
            ".",
            "owned 0700 directory",
            f"{type(error).__name__}: errno={error.errno}",
            partial=False,
        )
    expected = f"directory owner={os.geteuid()} mode=0700"
    actual = f"mode={stat.S_IMODE(metadata.st_mode):04o} owner={metadata.st_uid}"
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        _fail(descriptor, "validate-run-root", ".", expected, actual, partial=False)
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        _fail(descriptor, "validate-run-root", ".", expected, actual, partial=False)
    return metadata


def _require_run_path(
    descriptor: int,
    run_root: Path,
    root: os.stat_result,
    *,
    partial: bool,
) -> None:
    try:
        current = os.stat(run_root, follow_symlinks=False)
    except OSError as error:
        _fail(
            descriptor,
            "stat-run-path",
            str(run_root),
            "original run-root directory identity",
            f"{type(error).__name__}: errno={error.errno}",
            partial=partial,
        )
    expected = (
        f"device={root.st_dev} inode={root.st_ino} owner={os.geteuid()} mode=0700"
    )
    actual = (
        f"device={current.st_dev} inode={current.st_ino} "
        f"owner={current.st_uid} mode={stat.S_IMODE(current.st_mode):04o}"
    )
    if (
        not stat.S_ISDIR(current.st_mode)
        or current.st_dev != root.st_dev
        or current.st_ino != root.st_ino
        or current.st_uid != os.geteuid()
        or stat.S_IMODE(current.st_mode) != 0o700
    ):
        _fail(
            descriptor,
            "validate-run-path",
            str(run_root),
            expected,
            actual,
            partial=partial,
        )


def _require_members(
    descriptor: int,
    expected: frozenset[str],
    *,
    partial: bool,
) -> None:
    try:
        names, truncated = _bounded_member_names(descriptor, len(expected))
    except OSError as error:
        _fail(
            descriptor,
            "list-members",
            ".",
            repr(sorted(expected)),
            f"{type(error).__name__}: errno={error.errno}",
            partial=partial,
        )
    actual = frozenset(names)
    if truncated or actual != expected:
        rendered = (*names, MORE_MEMBERS) if truncated else names
        _fail(
            descriptor,
            "validate-members",
            ".",
            repr(sorted(expected)),
            repr(rendered),
            partial=partial,
        )


def _require_transients(descriptor: int, root: os.stat_result) -> None:
    for name in sorted(TRANSIENT_NAMES):
        try:
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except OSError as error:
            _fail(
                descriptor,
                "stat-transient",
                name,
                "owned 0700 directory on run-root device",
                f"{type(error).__name__}: errno={error.errno}",
                partial=False,
            )
        actual = (
            f"type={'directory' if stat.S_ISDIR(metadata.st_mode) else 'other'} "
            f"owner={metadata.st_uid} device={metadata.st_dev} "
            f"mode={stat.S_IMODE(metadata.st_mode):04o}"
        )
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_dev != root.st_dev
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            _fail(
                descriptor,
                "validate-transient",
                name,
                "owned 0700 directory on run-root device",
                actual,
                partial=False,
            )


def _tree_metadata(
    run_descriptor: int,
    parent_descriptor: int,
    name: str,
    relative: str,
    device: int,
    *,
    partial: bool,
) -> os.stat_result:
    try:
        metadata = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError as error:
        _fail(
            run_descriptor,
            "stat-transient-tree",
            relative,
            f"entry on run-root device={device}",
            f"{type(error).__name__}: errno={error.errno}",
            partial=partial,
        )
    if metadata.st_dev != device:
        _fail(
            run_descriptor,
            "validate-transient-tree",
            relative,
            f"entry on run-root device={device}",
            f"device={metadata.st_dev}",
            partial=partial,
        )
    return metadata


def _open_tree_directory(
    run_descriptor: int,
    parent_descriptor: int,
    name: str,
    relative: str,
    metadata: os.stat_result,
    *,
    partial: bool,
) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = -1
    try:
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
        observed = os.fstat(descriptor)
    except OSError as error:
        if descriptor >= 0:
            os.close(descriptor)
        _fail(
            run_descriptor,
            "open-transient-tree",
            relative,
            "stable directory opened without following symlinks",
            f"{type(error).__name__}: errno={error.errno}",
            partial=partial,
        )
    if (
        not stat.S_ISDIR(observed.st_mode)
        or observed.st_dev != metadata.st_dev
        or observed.st_ino != metadata.st_ino
    ):
        os.close(descriptor)
        _fail(
            run_descriptor,
            "validate-transient-tree",
            relative,
            f"stable directory device={metadata.st_dev} inode={metadata.st_ino}",
            f"device={observed.st_dev} inode={observed.st_ino}",
            partial=partial,
        )
    return descriptor


def _directory_entries(
    descriptor: int,
) -> Generator[os.DirEntry[str]]:
    with os.scandir(descriptor) as entries:
        yield from entries


def _close_walk(
    stack: list[tuple[int, Generator[os.DirEntry[str]], str]],
) -> None:
    while stack:
        descriptor, entries, _relative = stack.pop()
        entries.close()
        try:
            os.close(descriptor)
        except OSError:
            pass


def _require_transient_tree(
    descriptor: int,
    root: os.stat_result,
    name: str,
    *,
    partial: bool,
) -> None:
    metadata = _tree_metadata(
        descriptor,
        descriptor,
        name,
        name,
        root.st_dev,
        partial=partial,
    )
    tree_descriptor = _open_tree_directory(
        descriptor,
        descriptor,
        name,
        name,
        metadata,
        partial=partial,
    )
    stack = [(tree_descriptor, _directory_entries(tree_descriptor), name)]
    try:
        while stack:
            parent, entries, relative = stack[-1]
            try:
                entry = next(entries)
            except StopIteration:
                finished, finished_entries, _ = stack.pop()
                finished_entries.close()
                os.close(finished)
                continue
            nested = f"{relative}/{entry.name}"[:MAX_DIAGNOSTIC_TEXT]
            child = _tree_metadata(
                descriptor,
                parent,
                entry.name,
                nested,
                root.st_dev,
                partial=partial,
            )
            if stat.S_ISDIR(child.st_mode):
                child_descriptor = _open_tree_directory(
                    descriptor,
                    parent,
                    entry.name,
                    nested,
                    child,
                    partial=partial,
                )
                stack.append(
                    (
                        child_descriptor,
                        _directory_entries(child_descriptor),
                        nested,
                    )
                )
    except OSError as error:
        _fail(
            descriptor,
            "scan-transient-tree",
            stack[-1][2] if stack else name,
            f"stable entries on run-root device={root.st_dev}",
            f"{type(error).__name__}: errno={error.errno}",
            partial=partial,
        )
    finally:
        _close_walk(stack)


def _require_transient_trees(
    descriptor: int,
    root: os.stat_result,
    *,
    partial: bool,
) -> None:
    for name in sorted(TRANSIENT_NAMES):
        _require_transient_tree(descriptor, root, name, partial=partial)


def _open_evidence(descriptor: int, name: str, *, partial: bool) -> int:
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        return os.open(name, flags, dir_fd=descriptor)
    except OSError as error:
        _fail(
            descriptor,
            "open-evidence",
            name,
            "regular owned 0600 file opened without following symlinks",
            f"{type(error).__name__}: errno={error.errno}",
            partial=partial,
        )


def _read_evidence(
    descriptor: int,
    evidence_descriptor: int,
    name: str,
    expected: bytes,
    *,
    partial: bool,
) -> tuple[bytes, os.stat_result, os.stat_result]:
    try:
        before = os.fstat(evidence_descriptor)
        chunks: list[bytes] = []
        remaining = MAX_EVIDENCE_BYTES + 1
        while remaining:
            chunk = os.read(evidence_descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(evidence_descriptor)
    except OSError as error:
        _fail(
            descriptor,
            "read-evidence",
            name,
            "stable expected bytes",
            f"{type(error).__name__}: errno={error.errno}",
            partial=partial,
        )
    return b"".join(chunks), before, after


def _identity(metadata: os.stat_result, raw: bytes) -> EvidenceIdentity:
    return EvidenceIdentity(
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_uid,
        metadata.st_nlink,
        stat.S_IMODE(metadata.st_mode),
        metadata.st_size,
        hashlib.sha256(raw).hexdigest(),
        metadata.st_ctime_ns,
        metadata.st_mtime_ns,
    )


def _same_identity_after_rename(
    observed: EvidenceIdentity, prior: EvidenceIdentity
) -> bool:
    return (
        observed.device,
        observed.inode,
        observed.owner,
        observed.links,
        observed.mode,
        observed.size,
        observed.sha256,
        observed.mtime_ns,
    ) == (
        prior.device,
        prior.inode,
        prior.owner,
        prior.links,
        prior.mode,
        prior.size,
        prior.sha256,
        prior.mtime_ns,
    )


def _observe_evidence(
    descriptor: int,
    root: os.stat_result,
    name: str,
    expected: bytes,
    *,
    partial: bool,
    prior: EvidenceIdentity | None = None,
    renamed: bool = False,
) -> EvidenceIdentity:
    if len(expected) > MAX_EVIDENCE_BYTES:
        _fail(
            descriptor,
            "validate-evidence-size",
            name,
            f"at most {MAX_EVIDENCE_BYTES} bytes",
            f"expected bytes={len(expected)}",
            partial=partial,
        )
    evidence_descriptor = _open_evidence(descriptor, name, partial=partial)
    try:
        raw, before, after = _read_evidence(
            descriptor, evidence_descriptor, name, expected, partial=partial
        )
    finally:
        try:
            os.close(evidence_descriptor)
        except OSError:
            pass
    observed = _identity(after, raw)
    stable = _identity(before, raw) == observed
    valid = (
        stable
        and stat.S_ISREG(after.st_mode)
        and observed.owner == os.geteuid()
        and observed.links == 1
        and observed.device == root.st_dev
        and observed.mode == 0o600
        and observed.size == len(expected)
        and raw == expected
    )
    prior_matches = prior is None or observed == prior
    if renamed and prior is not None:
        prior_matches = _same_identity_after_rename(observed, prior)
    if not valid or not prior_matches:
        _fail(
            descriptor,
            "validate-evidence",
            name,
            f"stable expected bytes owner={os.geteuid()} device={root.st_dev} "
            "links=1 mode=0600",
            repr(observed),
            partial=partial,
        )
    return observed


def _fsync_evidence(
    descriptor: int,
    name: str,
    *,
    partial: bool,
) -> None:
    evidence_descriptor = _open_evidence(descriptor, name, partial=partial)
    try:
        os.fsync(evidence_descriptor)
    except OSError as error:
        _fail(
            descriptor,
            "fsync-evidence",
            name,
            "evidence bytes durable",
            f"{type(error).__name__}: errno={error.errno}",
            partial=partial,
        )
    finally:
        try:
            os.close(evidence_descriptor)
        except OSError:
            pass


def _remove_transients(descriptor: int, root: os.stat_result) -> None:
    removed = False
    for name in sorted(TRANSIENT_NAMES):
        _require_transient_tree(descriptor, root, name, partial=removed)
        try:
            shutil.rmtree(name, dir_fd=descriptor)
        except OSError as error:
            _fail(
                descriptor,
                "delete-transient",
                name,
                "symlink-safe recursive deletion",
                f"{type(error).__name__}: errno={error.errno}",
                partial=True,
            )
        removed = True


def _write_all(descriptor: int, raw: bytes) -> None:
    view = memoryview(raw)
    written = 0
    while written < len(raw):
        count = os.write(descriptor, view[written:])
        if count < 1:
            raise OSError("short write while publishing clean-room proof")
        written += count


def require_evidence_bounds(source_manifest: bytes, proof: bytes) -> None:
    for name, payload in (
        (SOURCE_MANIFEST_NAME, source_manifest),
        (PROOF_NAME, proof),
    ):
        if len(payload) > MAX_EVIDENCE_BYTES:
            raise CleanRoomRetentionError(
                "validate-evidence-size",
                name,
                f"at most {MAX_EVIDENCE_BYTES} bytes",
                f"expected bytes={len(payload)}",
                partial_cleanup_applied=False,
                remaining_members=(),
            )


def _discard_proof(descriptor: int) -> str:
    failures: list[str] = []
    for name in (PROOF_NAME, PROOF_TEMP_NAME):
        try:
            os.unlink(name, dir_fd=descriptor)
        except FileNotFoundError:
            continue
        except OSError as error:
            failures.append(f"{name}:{type(error).__name__}:{error.errno}")
    try:
        os.fsync(descriptor)
    except OSError as error:
        failures.append(
            f"directory-fsync:{type(error).__name__}:{error.errno}:durability=UNKNOWN"
        )
    return ";".join(failures)


def _after_proof_cleanup(
    error: CleanRoomRetentionError,
    descriptor: int,
    cleanup: str,
) -> CleanRoomRetentionError:
    actual = f"{error.actual}; proof_cleanup={cleanup or 'PASS'}"
    return CleanRoomRetentionError(
        error.operation,
        error.entry,
        error.expected,
        actual,
        partial_cleanup_applied=error.partial_cleanup_applied,
        remaining_members=_remaining_members(descriptor),
    )


def _prepare_proof(
    descriptor: int,
    proof: bytes,
) -> EvidenceIdentity:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    proof_descriptor = -1
    try:
        proof_descriptor = os.open(PROOF_TEMP_NAME, flags, 0o600, dir_fd=descriptor)
        _write_all(proof_descriptor, proof)
        os.fsync(proof_descriptor)
        os.lseek(proof_descriptor, 0, os.SEEK_SET)
        raw, before, after = _read_evidence(
            descriptor, proof_descriptor, PROOF_TEMP_NAME, proof, partial=True
        )
        identity = _identity(after, raw)
        if _identity(before, raw) != identity or raw != proof:
            _fail(
                descriptor,
                "validate-pending-proof",
                PROOF_TEMP_NAME,
                "stable expected proof bytes",
                repr(identity),
                partial=True,
            )
        identity = _identity(os.fstat(proof_descriptor), raw)
    except CleanRoomRetentionError as error:
        cleanup = _discard_proof(descriptor)
        raise _after_proof_cleanup(error, descriptor, cleanup) from error
    except OSError as error:
        cleanup = _discard_proof(descriptor)
        _fail(
            descriptor,
            "prepare-proof",
            PROOF_TEMP_NAME,
            "durable exact pending proof bytes",
            f"{type(error).__name__}: errno={error.errno}; cleanup={cleanup or 'PASS'}",
            partial=True,
        )
    finally:
        if proof_descriptor >= 0:
            try:
                os.close(proof_descriptor)
            except OSError:
                pass
    return identity


def _commit_proof(descriptor: int) -> None:
    try:
        os.rename(
            PROOF_TEMP_NAME,
            PROOF_NAME,
            src_dir_fd=descriptor,
            dst_dir_fd=descriptor,
        )
    except OSError as error:
        _fail(
            descriptor,
            "publish-proof",
            PROOF_NAME,
            "atomic pending-to-final proof rename",
            f"{type(error).__name__}: errno={error.errno}",
            partial=True,
        )


def _compact_transient_state(
    descriptor: int,
    run_root: Path,
    source_manifest: bytes,
) -> tuple[os.stat_result, EvidenceIdentity]:
    root = _require_run_root(descriptor)
    _require_run_path(descriptor, run_root, root, partial=False)
    _require_members(descriptor, INITIAL_NAMES, partial=False)
    source_identity = _observe_evidence(
        descriptor, root, SOURCE_MANIFEST_NAME, source_manifest, partial=False
    )
    _require_transients(descriptor, root)
    _fsync_evidence(descriptor, SOURCE_MANIFEST_NAME, partial=False)
    _observe_evidence(
        descriptor,
        root,
        SOURCE_MANIFEST_NAME,
        source_manifest,
        partial=False,
        prior=source_identity,
    )
    _require_transient_trees(descriptor, root, partial=False)
    _remove_transients(descriptor, root)
    _require_members(descriptor, frozenset({SOURCE_MANIFEST_NAME}), partial=True)
    _observe_evidence(
        descriptor,
        root,
        SOURCE_MANIFEST_NAME,
        source_manifest,
        partial=True,
        prior=source_identity,
    )
    _fsync_evidence(descriptor, SOURCE_MANIFEST_NAME, partial=True)
    return root, source_identity


def _fsync_run_root(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError as error:
        _fail(
            descriptor,
            "fsync-run-root",
            ".",
            "final evidence directory durable",
            f"{type(error).__name__}: errno={error.errno}",
            partial=True,
        )


def _finalize_evidence(
    descriptor: int,
    run_root: Path,
    root: os.stat_result,
    source_identity: EvidenceIdentity,
    source_manifest: bytes,
    proof: bytes,
) -> None:
    try:
        proof_identity = _prepare_proof(descriptor, proof)
        _observe_evidence(
            descriptor,
            root,
            PROOF_TEMP_NAME,
            proof,
            partial=True,
            prior=proof_identity,
        )
        _observe_evidence(
            descriptor,
            root,
            SOURCE_MANIFEST_NAME,
            source_manifest,
            partial=True,
            prior=source_identity,
        )
        _require_members(
            descriptor,
            frozenset({SOURCE_MANIFEST_NAME, PROOF_TEMP_NAME}),
            partial=True,
        )
        _require_run_path(descriptor, run_root, root, partial=True)
        _fsync_run_root(descriptor)
        _commit_proof(descriptor)
        _observe_evidence(
            descriptor,
            root,
            PROOF_NAME,
            proof,
            partial=True,
            prior=proof_identity,
            renamed=True,
        )
        _observe_evidence(
            descriptor,
            root,
            SOURCE_MANIFEST_NAME,
            source_manifest,
            partial=True,
            prior=source_identity,
        )
        _require_members(descriptor, EVIDENCE_NAMES, partial=True)
        _require_run_path(descriptor, run_root, root, partial=True)
        _fsync_run_root(descriptor)
    except CleanRoomRetentionError as error:
        cleanup = _discard_proof(descriptor)
        raise _after_proof_cleanup(error, descriptor, cleanup) from error


def compact_successful_run(
    run_root: Path,
    *,
    source_manifest: bytes,
    proof: bytes,
) -> None:
    require_evidence_bounds(source_manifest, proof)
    if not SYMLINK_SAFE_RMTREE:
        raise CleanRoomRetentionError(
            "preflight",
            ".",
            "symlink-safe recursive deletion available",
            "shutil.rmtree.avoids_symlink_attacks=False",
            partial_cleanup_applied=False,
            remaining_members=(),
        )
    descriptor = _open_run_root(run_root)
    try:
        root, source_identity = _compact_transient_state(
            descriptor, run_root, source_manifest
        )
        _finalize_evidence(
            descriptor,
            run_root,
            root,
            source_identity,
            source_manifest,
            proof,
        )
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
