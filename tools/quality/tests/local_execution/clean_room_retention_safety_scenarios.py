import os
from pathlib import Path

import pytest

from tools.local_execution import clean_room_retention as retention_module
from tools.local_execution.clean_room_retention import (
    MORE_MEMBERS,
    PROOF_NAME,
    PROOF_TEMP_NAME,
    SOURCE_MANIFEST_NAME,
    TRANSIENT_NAMES,
    CleanRoomRetentionError,
    compact_successful_run,
)
from tools.quality.tests.local_execution.assertions import (
    assert_equal,
    assert_false,
    assert_raises,
    assert_true,
)
from tools.quality.tests.local_execution.reporting import scenario

SOURCE_BYTES = b'{"manifest":"trusted"}\n'
PROOF_BYTES = b'{"status":"PASS"}\n'


def _retention_root(parent: Path, name: str) -> Path:
    root = parent / name
    root.mkdir(mode=0o700)
    source = root / SOURCE_MANIFEST_NAME
    source.write_bytes(SOURCE_BYTES)
    source.chmod(0o600)
    for transient_name in TRANSIENT_NAMES:
        transient = root / transient_name
        transient.mkdir(mode=0o700)
        (transient / "payload").write_bytes(b"diagnostic payload\n")
    return root


def _retention_error(root: Path, label: str) -> CleanRoomRetentionError:
    def compact() -> None:
        compact_successful_run(
            root,
            source_manifest=SOURCE_BYTES,
            proof=PROOF_BYTES,
        )

    return assert_raises(CleanRoomRetentionError, compact, label)


def _different_device(metadata: os.stat_result) -> os.stat_result:
    return os.stat_result(
        (
            metadata.st_mode,
            metadata.st_ino,
            metadata.st_dev + 1,
            metadata.st_nlink,
            metadata.st_uid,
            metadata.st_gid,
            metadata.st_size,
            metadata.st_atime,
            metadata.st_mtime,
            metadata.st_ctime,
        )
    )


def _assert_preflight_state(root: Path, label: str) -> None:
    assert_true(
        all((root / name).is_dir() for name in TRANSIENT_NAMES),
        f"{label}: transients preserved",
    )
    assert_false((root / PROOF_NAME).exists(), f"{label}: PASS absent")


@scenario(
    "LF-N43",
    "Отклонять вложенное устройство до recursive retention",
    feature="Воспроизводимость",
)
def verify_nested_device_retention_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _retention_root(tmp_path, "nested-device")
    original_stat = os.stat

    def nested_device(
        path: str | os.PathLike[str],
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        metadata = original_stat(
            path,
            dir_fd=dir_fd,
            follow_symlinks=follow_symlinks,
        )
        if path == "payload" and dir_fd is not None:
            return _different_device(metadata)
        return metadata

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "stat", nested_device)
        error = _retention_error(root, "nested mount device")
    assert_equal(error.operation, "validate-transient-tree", "device operation")
    assert_false(error.partial_cleanup_applied, "device preflight before deletion")
    _assert_preflight_state(root, "nested device rejection")


@scenario(
    "LF-N44",
    "Ограничивать диагностику неоднозначного run-root состава",
    feature="Воспроизводимость",
)
def verify_bounded_retention_membership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _retention_root(tmp_path, "bounded-membership")
    for number in range(64):
        (root / f"unexpected-{number:02d}").write_text("unexpected\n", encoding="utf-8")

    def reject_listdir(_path: str | os.PathLike[str]) -> list[str]:
        raise AssertionError("retention must stream run-root membership")

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "listdir", reject_listdir)
        error = _retention_error(root, "bounded root membership")
    assert_equal(error.operation, "validate-members", "membership operation")
    assert_true(MORE_MEMBERS in error.remaining_members, "truncation marker")
    assert_true(len(error.remaining_members) <= 17, "bounded diagnostics")
    _assert_preflight_state(root, "bounded root membership")


@scenario(
    "LF-N46",
    "Отклонять oversized proof до удаления diagnostics",
    feature="Воспроизводимость",
)
def verify_proof_size_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _retention_root(tmp_path, "oversized-proof")
    with monkeypatch.context() as scoped:
        scoped.setattr(retention_module, "MAX_EVIDENCE_BYTES", 8)

        def compact() -> None:
            compact_successful_run(
                root,
                source_manifest=b"source\n",
                proof=b"oversized proof\n",
            )

        error = assert_raises(CleanRoomRetentionError, compact, "proof size preflight")
    assert_equal(error.operation, "validate-evidence-size", "proof size operation")
    assert_equal(error.entry, PROOF_NAME, "oversized evidence member")
    assert_false(error.partial_cleanup_applied, "no cleanup before size rejection")
    assert_false((root / PROOF_TEMP_NAME).exists(), "pending proof absent")
    _assert_preflight_state(root, "oversized proof")


@scenario(
    "LF-N52",
    "Отклонять oversized SOURCE_MANIFEST до записи и compaction",
    feature="Воспроизводимость",
)
def verify_source_manifest_size_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _retention_root(tmp_path, "oversized-source")
    source_path = root / SOURCE_MANIFEST_NAME
    source_path.write_bytes(b"original\n")
    source_path.chmod(0o600)
    with monkeypatch.context() as scoped:
        scoped.setattr(retention_module, "MAX_EVIDENCE_BYTES", 8)

        def compact() -> None:
            compact_successful_run(
                root,
                source_manifest=b"oversized source manifest\n",
                proof=b"proof\n",
            )

        error = assert_raises(
            CleanRoomRetentionError,
            compact,
            "source manifest size preflight",
        )
    assert_equal(error.operation, "validate-evidence-size", "source size operation")
    assert_equal(error.entry, SOURCE_MANIFEST_NAME, "oversized source member")
    assert_equal(source_path.read_bytes(), b"original\n", "source bytes unchanged")
    assert_false(error.partial_cleanup_applied, "no cleanup before source rejection")
    assert_false((root / PROOF_TEMP_NAME).exists(), "pending proof absent")
    _assert_preflight_state(root, "oversized source manifest")
