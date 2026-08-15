import errno
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import pytest

from tools.local_execution import clean_room as clean_room_module
from tools.local_execution import clean_room_source_supervisor as supervisor_module
from tools.local_execution.clean_room import CleanRoomError, prove_clean_room
from tools.local_execution.clean_room_retention import (
    CHECKOUT_NAMES,
    EVIDENCE_NAMES,
    PROOF_NAME,
    PROOF_TEMP_NAME,
    SOURCE_MANIFEST_NAME,
    TRANSIENT_NAMES,
    CleanRoomRetentionError,
    compact_successful_run,
    host_state_name,
)
from tools.local_execution.clean_room_source import discover_source_paths
from tools.quality.source_manifest import (
    SourceManifest,
    SourceManifestError,
    build_source_manifest,
    parse_source_manifest,
)
from tools.quality.tests.local_execution.assertions import (
    assert_contains,
    assert_equal,
    assert_false,
    assert_raises,
    assert_true,
)
from tools.quality.tests.local_execution.reporting import scenario, step_context

SOURCE_BYTES = b'{"manifest":"trusted"}\n'
PROOF_BYTES = b'{"status":"PASS"}\n'
FIFO_RETENTION_PROGRAM = """\
import sys
from pathlib import Path
from tools.local_execution.clean_room_retention import (
    CleanRoomRetentionError, compact_successful_run,
)
try:
    compact_successful_run(
        Path(sys.argv[1]),
        source_manifest=bytes.fromhex(sys.argv[2]),
        proof=bytes.fromhex(sys.argv[3]),
    )
except CleanRoomRetentionError as error:
    print(f'operation={error.operation}')
    print(f'partial={error.partial_cleanup_applied}')
    raise SystemExit(0)
raise SystemExit(2)
"""


@dataclass(frozen=True, slots=True)
class RetentionFixture:
    root: Path
    source_manifest: bytes = SOURCE_BYTES
    proof: bytes = PROOF_BYTES

    @property
    def source_path(self) -> Path:
        return self.root / SOURCE_MANIFEST_NAME

    @property
    def proof_path(self) -> Path:
        return self.root / PROOF_NAME


def _retention_fixture(parent: Path, name: str) -> RetentionFixture:
    root = parent / name
    root.mkdir(mode=0o700)
    source_path = root / SOURCE_MANIFEST_NAME
    source_path.write_bytes(SOURCE_BYTES)
    source_path.chmod(0o600)
    for transient_name in TRANSIENT_NAMES:
        transient = root / transient_name
        transient.mkdir(mode=0o700)
        (transient / "payload").write_bytes(b"diagnostic payload\n")
    return RetentionFixture(root)


def _compact(fixture: RetentionFixture) -> None:
    compact_successful_run(
        fixture.root,
        source_manifest=fixture.source_manifest,
        proof=fixture.proof,
    )


def _retention_error(fixture: RetentionFixture, label: str) -> CleanRoomRetentionError:
    return assert_raises(CleanRoomRetentionError, lambda: _compact(fixture), label)


def _fifo_retention_result(
    fixture: RetentionFixture,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (
            sys.executable,
            "-B",
            "-c",
            FIFO_RETENTION_PROGRAM,
            str(fixture.root),
            fixture.source_manifest.hex(),
            fixture.proof.hex(),
        ),
        cwd=Path.cwd(),
        capture_output=True,
        check=False,
        text=True,
        timeout=3,
    )


def _assert_no_pass(fixture: RetentionFixture, label: str) -> None:
    assert_false(fixture.proof_path.exists(), f"{label}: proof.json отсутствует")
    assert_false(
        (fixture.root / PROOF_TEMP_NAME).exists(),
        f"{label}: временный proof отсутствует",
    )


def _assert_transients_present(fixture: RetentionFixture, label: str) -> None:
    actual = frozenset(path.name for path in fixture.root.iterdir())
    assert_true(TRANSIENT_NAMES <= actual, f"{label}: transient данные сохранены")


def _signal_zero(identifier: int) -> None:
    os.kill(identifier, 0)


def _mutate_after_first_delete(
    fixture: RetentionFixture,
    monkeypatch: pytest.MonkeyPatch,
    mutation: Callable[[], None],
) -> CleanRoomRetentionError:
    original = shutil.rmtree
    calls = 0

    def delete(path: str, *, dir_fd: int | None = None) -> None:
        nonlocal calls
        original(path, dir_fd=dir_fd)
        calls += 1
        if calls == 1:
            mutation()

    with monkeypatch.context() as scoped:
        scoped.setattr(shutil, "rmtree", delete)
        return _retention_error(fixture, "подмена evidence во время compaction")


def _mutate_at_final_proof_commit(
    fixture: RetentionFixture,
    monkeypatch: pytest.MonkeyPatch,
    mutation: Callable[[], None],
) -> CleanRoomRetentionError:
    original = os.rename

    def mutate_then_commit(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        mutation()
        original(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "rename", mutate_then_commit)
        return _retention_error(fixture, "подмена при финальной публикации proof")


def _forced_delete_error(
    fixture: RetentionFixture,
    monkeypatch: pytest.MonkeyPatch,
    fail_at: int,
) -> CleanRoomRetentionError:
    original = shutil.rmtree
    calls = 0

    def delete(path: str, *, dir_fd: int | None = None) -> None:
        nonlocal calls
        calls += 1
        if calls == fail_at:
            child = os.open(
                path,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=dir_fd,
            )
            try:
                os.unlink("payload", dir_fd=child)
            finally:
                os.close(child)
            raise OSError(errno.EIO, "forced transient deletion failure")
        original(path, dir_fd=dir_fd)

    with monkeypatch.context() as scoped:
        scoped.setattr(shutil, "rmtree", delete)
        return _retention_error(fixture, f"сбой удаления номер {fail_at}")


def _crash_at_proof_commit(fixture: RetentionFixture, *, after_rename: bool) -> int:
    process = os.fork()
    if process == 0:
        original = os.rename

        def crash(
            source: str,
            destination: str,
            *,
            src_dir_fd: int | None = None,
            dst_dir_fd: int | None = None,
        ) -> None:
            if after_rename:
                original(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )
            os._exit(72 if after_rename else 71)

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(os, "rename", crash)
            _compact(fixture)
        os._exit(90)
    _, status = os.waitpid(process, 0)
    return os.waitstatus_to_exitcode(status)


def _replace_source_with_same_bytes(fixture: RetentionFixture) -> None:
    replacement = fixture.root / "replacement"
    replacement.write_bytes(fixture.source_manifest)
    replacement.chmod(0o600)
    replacement.replace(fixture.source_path)


def _replace_source_with_symlink(fixture: RetentionFixture, external: Path) -> None:
    fixture.source_path.unlink()
    fixture.source_path.symlink_to(external)


def _remove_source(fixture: RetentionFixture) -> None:
    fixture.source_path.unlink()


def _verify_hardlink_evidence_rejected(tmp_path: Path) -> None:
    with step_context("Отклонить внешний hardlink на evidence до удаления"):
        fixture = _retention_fixture(tmp_path, "hardlinked-source")
        external_alias = tmp_path / "external-manifest-alias"
        os.link(fixture.source_path, external_alias)
        error = _retention_error(fixture, "внешний hardlink evidence")
        assert_equal(error.operation, "validate-evidence", "hardlink operation")
        assert_false(error.partial_cleanup_applied, "hardlink partial cleanup")
        assert_equal(external_alias.read_bytes(), SOURCE_BYTES, "hardlink bytes")
        _assert_no_pass(fixture, "hardlink evidence")
        _assert_transients_present(fixture, "hardlink evidence")


@scenario(
    "LF-N24",
    "Публиковать PASS только после безопасной компактации",
    feature="Воспроизводимость",
)
def verify_retention_success_and_preflight(tmp_path: Path) -> None:
    with step_context("Подготовить приватный успешный clean-room запуск"):
        successful = _retention_fixture(tmp_path, "successful")
    with step_context("Сжать transient состояние и синхронизировать evidence"):
        _compact(successful)
    with step_context("Проверить точные сохранённые байты и состав каталога"):
        members = frozenset(path.name for path in successful.root.iterdir())
        assert_equal(members, EVIDENCE_NAMES, "состав сохранённого proof")
        assert_equal(
            successful.source_path.read_bytes(), SOURCE_BYTES, "SOURCE_MANIFEST bytes"
        )
        assert_equal(successful.proof_path.read_bytes(), PROOF_BYTES, "proof bytes")
    with step_context("Отклонить подмену manifest до первого удаления"):
        mutated = _retention_fixture(tmp_path, "mutated-source")
        mutated.source_path.write_bytes(b'{"manifest":"forged"}\n')
        error = _retention_error(mutated, "подменённый SOURCE_MANIFEST")
        assert_equal(error.operation, "validate-evidence", "операция ошибки")
        assert_false(error.partial_cleanup_applied, "удаление до проверки bytes")
        _assert_no_pass(mutated, "подмена source")
        _assert_transients_present(mutated, "подмена source")


@scenario(
    "LF-N25",
    "Отклонять неоднозначный состав и небезопасные evidence paths",
    feature="Воспроизводимость",
)
def verify_retention_membership_and_modes(tmp_path: Path) -> None:
    with step_context("Отклонить заранее созданный proof payload"):
        forged_proof = _retention_fixture(tmp_path, "forged-proof")
        forged_proof.proof_path.write_bytes(b'{"status":"PASS","forged":true}\n')
        error = _retention_error(forged_proof, "заранее созданный proof")
        assert_equal(error.operation, "validate-members", "proof mutation operation")
        _assert_transients_present(forged_proof, "заранее созданный proof")
    with step_context("Отклонить неожиданный участник без удаления диагностики"):
        unexpected = _retention_fixture(tmp_path, "unexpected-member")
        (unexpected.root / "unknown").write_text("unknown\n", encoding="utf-8")
        error = _retention_error(unexpected, "неожиданный участник")
        assert_equal(error.operation, "validate-members", "membership operation")
        _assert_transients_present(unexpected, "неожиданный участник")
    with step_context("Отклонить отсутствующий transient участник"):
        missing = _retention_fixture(tmp_path, "missing-member")
        missing_name = min(TRANSIENT_NAMES)
        shutil.rmtree(missing.root / missing_name)
        error = _retention_error(missing, "отсутствующий transient")
        assert_equal(error.operation, "validate-members", "missing member operation")
        _assert_no_pass(missing, "отсутствующий transient")
    with step_context("Отклонить ослабленный mode evidence до удаления"):
        unsafe_mode = _retention_fixture(tmp_path, "unsafe-mode")
        unsafe_mode.source_path.chmod(0o644)
        error = _retention_error(unsafe_mode, "небезопасный mode")
        assert_equal(error.operation, "validate-evidence", "mode operation")
        _assert_transients_present(unsafe_mode, "небезопасный mode")
        transient_mode = _retention_fixture(tmp_path, "unsafe-transient-mode")
        (transient_mode.root / min(TRANSIENT_NAMES)).chmod(0o755)
        error = _retention_error(transient_mode, "небезопасный transient mode")
        assert_equal(error.operation, "validate-transient", "transient mode operation")
        _assert_transients_present(transient_mode, "небезопасный transient mode")


@scenario(
    "LF-N30",
    "Отклонять FIFO evidence без блокировки retention",
    feature="Воспроизводимость",
)
def verify_fifo_evidence_is_bounded(tmp_path: Path) -> None:
    with step_context("Заменить SOURCE_MANIFEST именованным каналом"):
        fixture = _retention_fixture(tmp_path, "fifo-source")
        fixture.source_path.unlink()
        os.mkfifo(fixture.source_path, mode=0o600)
    with step_context("Выполнить public retention с внешним timeout"):
        result = _fifo_retention_result(fixture)
    with step_context("Проверить нормализованный RED без PASS и удаления"):
        assert_equal(result.returncode, 0, "FIFO retention subprocess exit")
        assert_contains("operation=validate-evidence", result.stdout, "FIFO operation")
        assert_contains("partial=False", result.stdout, "FIFO partial state")
        _assert_no_pass(fixture, "FIFO evidence")
        _assert_transients_present(fixture, "FIFO evidence")


@scenario(
    "LF-N26",
    "Обнаруживать TOCTOU подмены evidence без ложного PASS",
    feature="Воспроизводимость",
)
def verify_retention_attack_resistance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with step_context("Обнаружить замену SOURCE_MANIFEST новым inode"):
        replaced = _retention_fixture(tmp_path, "replaced-source")
        error = _mutate_after_first_delete(
            replaced, monkeypatch, lambda: _replace_source_with_same_bytes(replaced)
        )
        assert_equal(error.operation, "validate-evidence", "replacement operation")
        assert_true(error.partial_cleanup_applied, "replacement partial cleanup")
        _assert_no_pass(replaced, "replacement")
    with step_context("Не перейти по symlink и сохранить внешний canary"):
        linked = _retention_fixture(tmp_path, "linked-source")
        external = tmp_path / "external-canary"
        external.write_bytes(SOURCE_BYTES)
        error = _mutate_after_first_delete(
            linked,
            monkeypatch,
            lambda: _replace_source_with_symlink(linked, external),
        )
        assert_equal(error.operation, "open-evidence", "symlink operation")
        assert_equal(external.read_bytes(), SOURCE_BYTES, "внешний canary")
        _assert_no_pass(linked, "symlink replacement")
    _verify_hardlink_evidence_rejected(tmp_path)
    with step_context("Обнаружить исчезновение evidence после первого удаления"):
        disappeared = _retention_fixture(tmp_path, "disappeared-source")
        error = _mutate_after_first_delete(
            disappeared, monkeypatch, lambda: _remove_source(disappeared)
        )
        assert_equal(error.operation, "validate-members", "disappearance operation")
        assert_true(error.partial_cleanup_applied, "disappearance partial cleanup")
        _assert_no_pass(disappeared, "disappearance")
    with step_context("Обнаружить изменение proof bytes перед публикацией"):
        proof_mutated = _retention_fixture(tmp_path, "mutated-proof")
        original_lseek = os.lseek
        corrupted = False

        def corrupt_then_seek(descriptor: int, position: int, how: int) -> int:
            nonlocal corrupted
            if not corrupted and stat.S_ISREG(os.fstat(descriptor).st_mode):
                os.pwrite(descriptor, b"X" * len(PROOF_BYTES), 0)
                corrupted = True
            return original_lseek(descriptor, position, how)

        with monkeypatch.context() as scoped:
            scoped.setattr(os, "lseek", corrupt_then_seek)
            error = _retention_error(proof_mutated, "изменение pending proof")
        assert_equal(
            error.operation, "validate-pending-proof", "proof mutation operation"
        )
        _assert_no_pass(proof_mutated, "proof mutation")
    with step_context("Обнаружить замену самого run-root пути"):
        run_replaced = _retention_fixture(tmp_path, "replaced-run-root")
        moved = tmp_path / "moved-run-root"

        def replace_run_path() -> None:
            run_replaced.root.rename(moved)
            run_replaced.root.mkdir(mode=0o700)

        error = _mutate_after_first_delete(run_replaced, monkeypatch, replace_run_path)
        assert_equal(error.operation, "validate-run-path", "run path operation")
        _assert_no_pass(run_replaced, "run path replacement")
        assert_false((moved / PROOF_NAME).exists(), "moved run не содержит PASS")


@scenario(
    "LF-N31",
    "Не публиковать proof при сбое финального commit point",
    feature="Воспроизводимость",
)
def verify_post_publication_invariants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with step_context("Заменить SOURCE_MANIFEST на границе proof commit"):
        source_replaced = _retention_fixture(tmp_path, "post-publish-source")
        source_error = _mutate_at_final_proof_commit(
            source_replaced,
            monkeypatch,
            lambda: _replace_source_with_same_bytes(source_replaced),
        )
        assert_equal(source_error.operation, "validate-evidence", "source commit guard")
    with step_context("Заменить pending proof и успешно выполнить atomic rename"):
        proof_replaced = _retention_fixture(tmp_path, "post-publish-proof")

        def replace_pending_proof() -> None:
            pending = proof_replaced.root / PROOF_TEMP_NAME
            replacement = proof_replaced.root / "replacement"
            replacement.write_bytes(pending.read_bytes())
            replacement.chmod(0o600)
            replacement.replace(pending)

        proof_error = _mutate_at_final_proof_commit(
            proof_replaced, monkeypatch, replace_pending_proof
        )
        assert_equal(proof_error.operation, "validate-evidence", "proof commit guard")
    with step_context("Ослабить mode run-root на границе proof commit"):
        mode_changed = _retention_fixture(tmp_path, "post-publish-mode")
        mode_error = _mutate_at_final_proof_commit(
            mode_changed,
            monkeypatch,
            lambda: mode_changed.root.chmod(0o777),
        )
        assert_equal(mode_error.operation, "validate-run-path", "run-root commit guard")
    with step_context("Подтвердить durable rollback всех PASS файлов"):
        _assert_no_pass(source_replaced, "post-publish source replacement")
        _assert_no_pass(proof_replaced, "post-publish proof replacement")
        _assert_no_pass(mode_changed, "post-publish mode change")
        assert_contains("proof_cleanup=PASS", source_error.actual, "source rollback")
        assert_contains("proof_cleanup=PASS", proof_error.actual, "proof rollback")
        assert_contains("proof_cleanup=PASS", mode_error.actual, "mode rollback")
        mode_changed.root.chmod(0o700)


@scenario(
    "LF-N32",
    "Сохранять однозначное состояние при crash вокруг proof commit",
    feature="Воспроизводимость",
)
def verify_atomic_proof_crash_states(tmp_path: Path) -> None:
    with step_context("Прервать процесс непосредственно до atomic rename"):
        before = _retention_fixture(tmp_path, "crash-before-rename")
        assert_equal(_crash_at_proof_commit(before, after_rename=False), 71, "exit")
        assert_false(before.proof_path.exists(), "proof до commit отсутствует")
        assert_true((before.root / PROOF_TEMP_NAME).exists(), "pending сохранён")
    with step_context("Прервать процесс непосредственно после atomic rename"):
        after = _retention_fixture(tmp_path, "crash-after-rename")
        assert_equal(_crash_at_proof_commit(after, after_rename=True), 72, "exit")
        assert_equal(after.proof_path.read_bytes(), PROOF_BYTES, "proof bytes")
        assert_false((after.root / PROOF_TEMP_NAME).exists(), "pending отсутствует")
    with step_context("Проверить точный состав обоих crash-состояний"):
        assert_equal(
            frozenset(path.name for path in before.root.iterdir()),
            frozenset({SOURCE_MANIFEST_NAME, PROOF_TEMP_NAME}),
            "pre-commit members",
        )
        assert_equal(
            frozenset(path.name for path in after.root.iterdir()),
            EVIDENCE_NAMES,
            "post-commit members",
        )


def _verify_stat_read_and_fsync_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stat_failed = _retention_fixture(tmp_path, "stat-failure")
    original_stat = os.stat
    target = min(TRANSIENT_NAMES)

    def fail_stat(
        path: str,
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        if path == target and dir_fd is not None:
            raise OSError(errno.EIO, "forced stat failure")
        return original_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "stat", fail_stat)
        stat_error = _retention_error(stat_failed, "stat failure")
    assert_equal(stat_error.operation, "stat-transient", "stat operation")
    read_failed = _retention_fixture(tmp_path, "read-failure")

    def fail_read(descriptor: int, size: int) -> bytes:
        del descriptor, size
        raise OSError(errno.EIO, "forced evidence read failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "read", fail_read)
        read_error = _retention_error(read_failed, "read failure")
    assert_equal(read_error.operation, "read-evidence", "read operation")
    fsync_failed = _retention_fixture(tmp_path, "evidence-fsync-failure")
    original_fsync = os.fsync

    def fail_regular_fsync(descriptor: int) -> None:
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError(errno.EIO, "forced evidence fsync failure")
        original_fsync(descriptor)

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "fsync", fail_regular_fsync)
        fsync_error = _retention_error(fsync_failed, "evidence fsync failure")
    assert_equal(fsync_error.operation, "fsync-evidence", "fsync operation")
    _assert_transients_present(fsync_failed, "evidence fsync failure")
    final_fsync_failed = _retention_fixture(tmp_path, "pending-proof-fsync-failure")
    regular_fsync_calls = 0

    def fail_final_evidence_fsync(descriptor: int) -> None:
        nonlocal regular_fsync_calls
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            regular_fsync_calls += 1
            if regular_fsync_calls == 3:
                raise OSError(errno.EIO, "forced pending proof fsync failure")
        original_fsync(descriptor)

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "fsync", fail_final_evidence_fsync)
        final_error = _retention_error(final_fsync_failed, "pending proof fsync")
    assert_equal(final_error.operation, "prepare-proof", "pending fsync operation")
    assert_true(final_error.partial_cleanup_applied, "final fsync partial cleanup")
    _assert_no_pass(final_fsync_failed, "final evidence fsync failure")


def _verify_directory_fsync_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _retention_fixture(tmp_path, "directory-fsync-failure")
    original_fsync = os.fsync
    directory_fsync_calls = 0

    def fail_directory_fsync(descriptor: int) -> None:
        nonlocal directory_fsync_calls
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_fsync_calls += 1
            if directory_fsync_calls == 1:
                raise OSError(errno.EIO, "forced directory fsync failure")
        original_fsync(descriptor)

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "fsync", fail_directory_fsync)
        error = _retention_error(fixture, "directory fsync failure")
    assert_equal(error.operation, "fsync-run-root", "directory fsync operation")
    assert_equal(directory_fsync_calls, 2, "failure plus cleanup directory fsync")
    assert_contains("proof_cleanup=PASS", error.actual, "durable proof cleanup")
    _assert_no_pass(fixture, "directory fsync failure")
    assert_equal(
        frozenset(path.name for path in fixture.root.iterdir()),
        frozenset({SOURCE_MANIFEST_NAME}),
        "состав после directory fsync failure",
    )
    unknown = _retention_fixture(tmp_path, "cleanup-fsync-failure")

    def fail_every_directory_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError(errno.EIO, "forced cleanup fsync failure")
        original_fsync(descriptor)

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "fsync", fail_every_directory_fsync)
        unknown_error = _retention_error(unknown, "cleanup fsync failure")
    assert_contains("durability=UNKNOWN", unknown_error.actual, "cleanup durability")
    _assert_no_pass(unknown, "cleanup fsync failure")


@scenario(
    "LF-N27",
    "Нормализовать частичные и системные ошибки retention",
    feature="Воспроизводимость",
)
def verify_retention_failure_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with step_context("Нормализовать сбой первого transient удаления"):
        first = _retention_fixture(tmp_path, "first-delete-failure")
        error = _forced_delete_error(first, monkeypatch, 1)
        assert_equal(error.operation, "delete-transient", "first delete operation")
        assert_true(error.partial_cleanup_applied, "first delete partial state")
        _assert_no_pass(first, "first deletion failure")
    with step_context("Зафиксировать честное состояние после второго сбоя"):
        second = _retention_fixture(tmp_path, "second-delete-failure")
        error = _forced_delete_error(second, monkeypatch, 2)
        assert_equal(error.operation, "delete-transient", "second delete operation")
        assert_true(error.partial_cleanup_applied, "second delete partial state")
        assert_equal(
            frozenset(error.remaining_members),
            frozenset(path.name for path in second.root.iterdir()),
            "remaining members после partial cleanup",
        )
        _assert_no_pass(second, "second deletion failure")
    with step_context("Нормализовать stat и evidence fsync ошибки"):
        _verify_stat_read_and_fsync_errors(tmp_path, monkeypatch)
    with step_context("Удалить видимый PASS при сбое fsync каталога"):
        _verify_directory_fsync_error(tmp_path, monkeypatch)


def _source_tree(root: Path) -> None:
    for relative in (
        ".tmp/generated.py",
        ".venv/generated.py",
        "package/__pycache__/generated.py",
        "package/.mypy_cache/generated.py",
        "package/vendor/real.py",
        "package/generated/real.py",
        "package/nested/.venv/real.py",
        "package/bytecode.pyc",
        "root.py",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("value = 1\n", encoding="utf-8")


def _verify_no_git_ruff_exclusions(root: Path) -> None:
    quality = root / "tools" / "quality"
    quality.mkdir(parents=True)
    (root / "pyproject.toml").write_bytes(Path("pyproject.toml").read_bytes())
    (quality / "ruff-lint.toml").write_bytes(
        Path("tools/quality/ruff-lint.toml").read_bytes()
    )
    kept = root / "kept.py"
    kept.write_text("value = 1\n", encoding="utf-8")
    nested_venv = root / "package" / "nested" / ".venv" / "real.py"
    nested_venv.parent.mkdir(parents=True)
    nested_venv.write_text("value = 1\n", encoding="utf-8")
    for excluded in (".cache", ".flare", ".tmp", ".venv"):
        generated = root / excluded / "generated.py"
        generated.parent.mkdir()
        generated.write_text("value = 1\n", encoding="utf-8")
    result = subprocess.run(
        (
            sys.executable,
            "-B",
            "-m",
            "ruff",
            "check",
            "--show-files",
            "--no-respect-gitignore",
            "--config",
            "tools/quality/ruff-lint.toml",
            ".",
        ),
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert_equal(result.returncode, 0, "Ruff no-Git discovery exit")
    listed = frozenset(Path(line).resolve() for line in result.stdout.splitlines())
    assert_true(kept.resolve() in listed, "Ruff retained source")
    assert_true(nested_venv.resolve() in listed, "Ruff retained nested .venv source")
    for excluded in (".cache", ".flare", ".tmp", ".venv"):
        generated = (root / excluded / "generated.py").resolve()
        assert_false(generated in listed, f"Ruff excluded {excluded}")


def _manifest_from_discovery(root: Path) -> SourceManifest:
    return build_source_manifest(root, discover_source_paths(root))


def _verify_source_manifest_symlink_boundaries(tmp_path: Path) -> None:
    source = tmp_path / "confined-symlink-source"
    (source / "content").mkdir(parents=True)
    (source / "links").mkdir()
    (source / "content" / "value.txt").write_text("inside\n", encoding="utf-8")
    internal_target = "../content/value.txt"
    (source / "links" / "value-link").symlink_to(internal_target)
    manifest = _manifest_from_discovery(source)
    materialized = tmp_path / "confined-symlink-copy"
    clean_room_module._materialize(source, materialized, manifest)
    assert_equal(
        os.readlink(materialized / "links" / "value-link"),
        internal_target,
        "verbatim confined symlink target",
    )

    canary = tmp_path / "external-symlink-canary"
    canary.write_text("must survive\n", encoding="utf-8")
    cases = (
        ("relative-escape", "../external-symlink-canary", "escapes root"),
        ("absolute-external", str(canary), "absolute source symlink"),
    )
    for label, target, expected in cases:
        root = tmp_path / f"symlink-{label}"
        root.mkdir()
        (root / "link").symlink_to(target)
        error = assert_raises(
            SourceManifestError,
            partial(_manifest_from_discovery, root),
            label,
        )
        assert_contains(expected, str(error), label)

    local = tmp_path / "symlink-absolute-local"
    local.mkdir()
    (local / "target").write_text("local\n", encoding="utf-8")
    (local / "link").symlink_to(local / "target")
    local_error = assert_raises(
        SourceManifestError,
        lambda: _manifest_from_discovery(local),
        "absolute local symlink",
    )
    assert_contains("absolute source symlink", str(local_error), "absolute local")

    chain = tmp_path / "symlink-chain"
    chain.mkdir()
    (chain / "first").symlink_to("second")
    (chain / "second").symlink_to("../external-symlink-canary")
    chain_error = assert_raises(
        SourceManifestError,
        lambda: _manifest_from_discovery(chain),
        "escaping symlink chain",
    )
    assert_contains("escapes root", str(chain_error), "escaping chain")

    loop = tmp_path / "symlink-loop"
    loop.mkdir()
    (loop / "first").symlink_to("second")
    (loop / "second").symlink_to("first")
    loop_error = assert_raises(
        SourceManifestError,
        lambda: _manifest_from_discovery(loop),
        "symlink loop",
    )
    assert_contains("cannot be resolved", str(loop_error), "symlink loop")
    assert_equal(canary.read_text(encoding="utf-8"), "must survive\n", "canary")


def _verify_source_manifest_modes(tmp_path: Path) -> None:
    root = tmp_path / "source-mode-identity"
    root.mkdir()
    source = root / "source.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    source.chmod(0o644)
    regular = _manifest_from_discovery(root)
    source.chmod(0o755)
    executable = _manifest_from_discovery(root)
    assert_false(regular.sha256 == executable.sha256, "mode changes manifest identity")
    assert_equal(regular.document.files[0].mode, 0o644, "regular source mode")
    assert_equal(executable.document.files[0].mode, 0o755, "executable source mode")
    for invalid in ("../escape", "/absolute", "nested//alias"):
        error = assert_raises(
            SourceManifestError,
            partial(build_source_manifest, root, (invalid,)),
            f"invalid source path {invalid}",
        )
        assert_contains("source path", str(error), "canonical source path")

    legacy = (
        b'{"files":[],"hash_algorithm":"sha256","manifest_sha256":"'
        + (b"0" * 64)
        + b'","version":1}\n'
    )
    assert_raises(
        ValueError, lambda: parse_source_manifest(legacy), "version-1 manifest"
    )
    missing_mode = (
        b'{"files":[{"bytes":0,"kind":"file","path":"source.py","sha256":"'
        + (b"0" * 64)
        + b'"}],"hash_algorithm":"sha256","manifest_sha256":"'
        + (b"0" * 64)
        + b'","version":2}\n'
    )
    assert_raises(
        ValueError, lambda: parse_source_manifest(missing_mode), "missing mode"
    )


@scenario(
    "LF-N28",
    "Отсекать generated roots до обхода исходников",
    feature="Воспроизводимость",
)
def verify_source_discovery_pruning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "source-tree"
    root.mkdir()
    _source_tree(root)
    with step_context("Подтвердить top-down pruning счётчиком обхода"):
        visited: list[str] = []

        def counting_walk(
            walk_root: Path,
            *,
            topdown: bool,
            onerror: Callable[[OSError], None] | None,
            followlinks: bool,
        ) -> Iterator[tuple[str, list[str], list[str]]]:
            assert_true(topdown, "top-down walk")
            assert_true(onerror is not None, "walk error boundary")
            assert_false(followlinks, "symlink traversal")
            directories = [".tmp", "package"]
            yield str(walk_root), directories, ["root.py"]
            visited.extend(directories)
            for name in directories:
                yield str(walk_root / name), [], []

        with monkeypatch.context() as scoped:
            scoped.setattr(os, "walk", counting_walk)
            discover_source_paths(root)
        assert_false(".tmp" in visited, "excluded root не посещён")
        assert_true("package" in visited, "source root посещён")
    with step_context("Исключить root и nested cache каталоги"):
        paths = frozenset(discover_source_paths(root))
        assert_false(any(path.startswith(".tmp/") for path in paths), ".tmp paths")
        assert_false(any("__pycache__" in path for path in paths), "pycache paths")
        assert_false(any(".mypy_cache" in path for path in paths), "mypy cache paths")
        assert_false("package/bytecode.pyc" in paths, "bytecode path")
    with step_context("Сохранить legitimate vendor и generated source"):
        assert_true("package/vendor/real.py" in paths, "vendor source")
        assert_true("package/generated/real.py" in paths, "generated source")
        assert_true("package/nested/.venv/real.py" in paths, "nested .venv source")
    with step_context("Сохранить symlink как identity и не обходить target"):
        external = tmp_path / "external-source"
        external.mkdir()
        (external / "external.py").write_text("external = 1\n", encoding="utf-8")
        (root / "linked-source").symlink_to(external, target_is_directory=True)
        linked_paths = frozenset(discover_source_paths(root))
        assert_true("linked-source" in linked_paths, "source symlink identity")
        assert_false(
            "linked-source/external.py" in linked_paths,
            "source symlink target traversal",
        )
    with step_context("Исключить generated roots из Ruff вне Git checkout"):
        _verify_no_git_ruff_exclusions(tmp_path / "ruff-source")
    with step_context("Разрешить только переносимые confined source symlinks"):
        _verify_source_manifest_symlink_boundaries(tmp_path)
    with step_context("Включить mode в source identity и schema v2"):
        _verify_source_manifest_modes(tmp_path)


def _write_public_fixture(root: Path) -> Path:
    root.mkdir()
    (root / ".gitignore").write_text(
        ".cache/\n.flare/\n.tmp/\n.venv/\n", encoding="utf-8"
    )
    (root / "Makefile").write_text(
        ".PHONY: check-fast\ncheck-fast:\n\t@./flare check-fast\n",
        encoding="utf-8",
    )
    (root / "source.txt").write_text("public integration source\n", encoding="utf-8")
    flare = root / "flare"
    flare.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        'case "${1:-}" in\n'
        "doctor)\n"
        "  if [ -f .flare/fixture-ready/ready ]; then echo doctor=PASS; exit 0; fi\n"
        "  echo doctor=FAIL; exit 1 ;;\n"
        "bootstrap)\n"
        "  mkdir -p .flare\n"
        "  if mkdir .flare/fixture-ready 2>/dev/null; then\n"
        "    touch .flare/fixture-ready/ready; action=CREATED\n"
        "  else\n"
        "    while [ ! -f .flare/fixture-ready/ready ]; do :; done; action=REUSED\n"
        "  fi\n"
        "  echo bootstrap=PASS; echo action=$action ;;\n"
        "check-fast) echo check-fast=PASS ;;\n"
        'environment-manifest) printf \'{"fixture":"stable"}\\n\' ;;\n'
        "*) exit 64 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    flare.chmod(0o755)
    subprocess.run(("git", "init", "-q"), cwd=root, check=True, timeout=10)
    subprocess.run(("git", "add", "-A"), cwd=root, check=True, timeout=10)
    uv = root.parent / "fixture-uv"
    uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)
    return uv


def _write_descendant_fixture(root: Path) -> Path:
    uv = _write_public_fixture(root)
    flare = root / "flare"
    flare.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        'case "${1:-}" in\n'
        "doctor)\n"
        "  setsid sh -c '\n"
        f"    while [ ! -e ../{SOURCE_MANIFEST_NAME} ]; do sleep 0.01; done\n"
        f"    printf forged > ../{SOURCE_MANIFEST_NAME}\n"
        "  ' &\n"
        "  printf '%s\\n' \"$!\" > descendant.pid\n"
        "  exit 1 ;;\n"
        "*) exit 64 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    flare.chmod(0o755)
    subprocess.run(("git", "add", "flare"), cwd=root, check=True, timeout=10)
    return uv


@scenario(
    "LF-N29",
    "Сохранить public prove_clean_room integration без приватного monkeypatch",
    feature="Воспроизводимость",
)
def verify_public_clean_room_integration(tmp_path: Path) -> None:
    with step_context("Подготовить минимальный Git checkout с публичным flare CLI"):
        source = tmp_path / "public-source"
        uv = _write_public_fixture(source)
    with step_context("Выполнить настоящий public prove_clean_room путь"):
        work_root = tmp_path / "public-proofs"
        result = prove_clean_room(source, work_root, uv)
    with step_context("Проверить durable PASS и точный retained состав"):
        proof_roots = tuple(work_root.iterdir())
        assert_equal(result["status"], "PASS", "public proof status")
        assert_equal(len(proof_roots), 1, "public proof directory count")
        retained = proof_roots[0]
        assert_equal(
            frozenset(path.name for path in retained.iterdir()),
            EVIDENCE_NAMES,
            "public retained members",
        )
        assert_contains(
            '"status": "PASS"', (retained / PROOF_NAME).read_text(), "proof"
        )


@scenario(
    "LF-N33",
    "Отклонять checkout с пережившей command process-group",
    feature="Воспроизводимость",
)
def verify_public_descendant_rejection(tmp_path: Path) -> None:
    with step_context("Отклонить недоступный self /proc supervision root"):

        def read_missing_self_state() -> None:
            supervisor_module._direct_children(os.getpid())

        def missing_proc_text(_path: Path, _deadline: float) -> str:
            raise FileNotFoundError

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(supervisor_module, "_proc_text", missing_proc_text)
            supervisor_error = assert_raises(
                supervisor_module.SupervisorError,
                read_missing_self_state,
                "missing self process state",
            )
        assert_contains(
            "self process", str(supervisor_error), "supervisor domain error"
        )
    with step_context("Подготовить checkout с delayed evidence writer"):
        source = tmp_path / "descendant-source"
        uv = _write_descendant_fixture(source)
        work_root = tmp_path / "descendant-proofs"
    with step_context("Выполнить только public prove_clean_room boundary"):

        def run_proof() -> None:
            prove_clean_room(source, work_root, uv)

        error = assert_raises(
            CleanRoomError,
            run_proof,
            "checkout descendant",
        )
        assert_contains("descendant process rejected", str(error), "domain error")
    with step_context("Проверить отсутствие writer и durable PASS"):
        proof_roots = tuple(work_root.iterdir())
        pid_files = tuple(work_root.rglob("descendant.pid"))
        assert_equal(len(proof_roots), 1, "diagnostic run roots")
        assert_true(bool(pid_files), "descendant PID evidence")
        for pid_file in pid_files:
            process = int(pid_file.read_text(encoding="utf-8").strip())
            assert_raises(
                ProcessLookupError,
                partial(_signal_zero, process),
                "descendant process absent",
            )
        retained_names = frozenset(path.name for path in proof_roots[0].iterdir())
        assert_false(SOURCE_MANIFEST_NAME in retained_names, "source not published")
        assert_false(PROOF_NAME in retained_names, "PASS not published")


@scenario(
    "LF-N34",
    "Отклонять позднюю мутацию уже завершённого twin checkout",
    feature="Воспроизводимость",
)
def verify_public_transient_replacement_rejection(tmp_path: Path) -> None:
    with step_context("Зафиксировать identities обоих завершённых checkout"):
        run_root = tmp_path / "completed-twins"
        run_root.mkdir(mode=0o700)
        proofs: list[clean_room_module.CheckoutProof] = []
        for name in CHECKOUT_NAMES:
            checkout = run_root / name
            host = run_root / host_state_name(name)
            checkout.mkdir(mode=0o700)
            host.mkdir(mode=0o700)
            tracked = checkout / "tracked.py"
            tracked.write_text("stable = True\n", encoding="utf-8")
            tracked.chmod(0o644)
            proofs.append(
                clean_room_module.CheckoutProof(
                    clean_room_module._directory_identity(checkout, name),
                    clean_room_module._directory_identity(host, name),
                    name,
                    clean_room_module._source_identity(checkout),
                    b"{}\n",
                    (),
                )
            )
    with step_context("Мутировать A после завершения обоих proofs и получить RED"):
        victim = run_root / CHECKOUT_NAMES[0] / "tracked.py"
        victim.write_text("stable = False\n", encoding="utf-8")

        def validate_completed_twins() -> None:
            clean_room_module._require_completed_checkout_identities(
                run_root, tuple(proofs)
            )

        error = assert_raises(CleanRoomError, validate_completed_twins, "late mutation")
        assert_contains("source identity changed", str(error), "domain error")
    with step_context("Отклонить mode-only мутацию завершённого checkout"):
        victim.write_text("stable = True\n", encoding="utf-8")
        victim.chmod(0o644)
        clean_room_module._require_completed_checkout_identities(
            run_root, tuple(proofs)
        )
        victim.chmod(0o755)
        mode_error = assert_raises(
            CleanRoomError,
            validate_completed_twins,
            "late executable-mode mutation",
        )
        assert_contains("source identity changed", str(mode_error), "mode domain error")
    with step_context("Не публиковать evidence при late mutation"):
        retained_names = frozenset(path.name for path in run_root.iterdir())
        assert_false(SOURCE_MANIFEST_NAME in retained_names, "source not published")
        assert_false(PROOF_NAME in retained_names, "PASS not published")
