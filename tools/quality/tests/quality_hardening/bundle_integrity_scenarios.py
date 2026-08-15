from __future__ import annotations

import os
import subprocess
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path

import pytest

from tools.platform.dependency_bundles import verify_bundle as verifier_module
from tools.platform.dependency_bundles.verify_bundle import check_archive
from tools.quality.tests.quality_hardening.assertions import (
    check_contains,
    check_equal,
    check_not_contains,
)
from tools.quality.tests.quality_hardening.bundle_integrity_fixtures import (
    BUNDLE_ROOT,
    ArchiveMember,
    canonical_manifest,
    checksum_record,
    file_digest,
    regular_bundle_files,
    restore_marker_script,
    run_restore_wrapper,
    write_archive_swap_shim,
    write_bundle,
    write_detached_checksum,
)
from tools.quality.tests.quality_hardening.reporting import (
    reported,
    step,
)
from tools.quality.tests.quality_hardening.scenario_catalog import (
    QH_N13,
    QH_N14,
    QH_N15,
    QH_N16,
)
from tools.quality.tests.quality_hardening.support import REPO_ROOT, QualityWorkspace

_ORIGINAL_MARKER = "ORIGINAL_VERIFIED_BUNDLE"
_REPLACEMENT_MARKER = "REPLACEMENT_UNVERIFIED_BUNDLE"


def _expect_rejected(archive: Path, expected: str, label: str) -> None:
    with pytest.raises(AssertionError) as captured:
        check_archive(archive)
    check_contains(expected, str(captured.value), label)


def _expect_cli_rejected(archive: Path, expected: str, label: str) -> None:
    verifier = REPO_ROOT / "tools/platform/dependency_bundles/verify_bundle.py"
    result = subprocess.run(
        (sys.executable, "-I", "-B", "-S", str(verifier), str(archive)),
        capture_output=True,
        check=False,
        text=True,
        timeout=5,
    )
    check_equal(result.returncode, 1, f"{label}: код завершения")
    check_contains(expected, result.stderr, label)


def _replace_first_record(
    manifest: str,
    *,
    digest: str | None = None,
    path: str | None = None,
    separator: str = "  ",
) -> str:
    first, *remaining = manifest.splitlines()
    current_digest, current_path = first.split("  ", 1)
    replacement = checksum_record(
        current_digest if digest is None else digest,
        current_path if path is None else path,
        separator,
    )
    return "\n".join((replacement, *remaining)) + "\n"


def _marker_bundle(directory: Path, marker: str) -> Path:
    files = regular_bundle_files(
        {
            "payload.txt": f"{marker}\n".encode(),
            "restore.sh": restore_marker_script(marker),
        }
    )
    return write_bundle(directory, regular_files=files)


def _check_restore_result(
    result: subprocess.CompletedProcess[str],
    target: Path,
    expected_marker: str,
    label: str,
) -> None:
    check_equal(result.returncode, 0, f"{label}: код завершения")
    check_contains("RESTORE WRAPPER PASS", result.stdout, f"{label}: сигнал wrapper")
    marker_path = target / "restore-marker"
    observed = marker_path.read_text(encoding="utf-8").strip()
    check_equal(observed, expected_marker, f"{label}: исполненные bundle-байты")


def _verify_restore_snapshot_binding(workspace: QualityWorkspace) -> None:
    wrapper = REPO_ROOT / "tools/platform/dependency_bundles/restore_role_bundle.sh"
    python = Path(sys.executable)
    control_archive = _marker_bundle(
        workspace.root / "bundle-restore-control",
        _ORIGINAL_MARKER,
    )
    control_target = workspace.root / "bundle-restore-control-target"
    control_target.mkdir()
    with step("Выполнить валидный restore из проверенного bundle"):
        result = run_restore_wrapper(
            wrapper,
            control_archive,
            control_target,
            python,
        )
        _check_restore_result(
            result, control_target, _ORIGINAL_MARKER, "control restore"
        )

    original = _marker_bundle(workspace.root / "bundle-race-original", _ORIGINAL_MARKER)
    replacement = _marker_bundle(
        workspace.root / "bundle-race-replacement",
        _REPLACEMENT_MARKER,
    )
    shim = write_archive_swap_shim(workspace.root / "swap-after-verification.sh")
    race_target = workspace.root / "bundle-race-target"
    race_target.mkdir()
    with step("Не переоткрывать заменённый archive после успешной проверки"):
        result = run_restore_wrapper(
            wrapper,
            original,
            race_target,
            shim,
            real_python=python,
            replacement=replacement,
        )
        check_equal(
            file_digest(original.read_bytes()),
            file_digest(replacement.read_bytes()),
            "Подмена archive path действительно произошла",
        )
        _check_restore_result(result, race_target, _ORIGINAL_MARKER, "snapshot restore")


def _verify_wrapper_symlink_rejection(workspace: QualityWorkspace) -> None:
    wrapper = REPO_ROOT / "tools/platform/dependency_bundles/restore_role_bundle.sh"
    regular = _marker_bundle(
        workspace.root / "bundle-wrapper-symlink-regular",
        _REPLACEMENT_MARKER,
    )
    alias = workspace.root / "bundle-wrapper-symlink.tar.gz"
    alias.symlink_to(regular)
    target = workspace.root / "bundle-wrapper-symlink-target"
    target.mkdir()
    with step("Отклонить archive symlink на consumer wrapper boundary"):
        result = run_restore_wrapper(
            wrapper,
            alias,
            target,
            Path(sys.executable),
        )
        check_equal(result.returncode, 1, "archive symlink: код завершения")
        check_contains("archive missing, unsafe", result.stderr, "archive symlink")
        check_equal(
            (target / "restore-marker").exists(),
            False,
            "archive symlink не исполнялся",
        )


def _verify_archive_path_semantics(workspace: QualityWorkspace) -> None:
    wrapper = REPO_ROOT / "tools/platform/dependency_bundles/restore_role_bundle.sh"
    base = workspace.root / "bundle-path-semantics-base"
    other = workspace.root / "bundle-path-semantics-other"
    _marker_bundle(base, _REPLACEMENT_MARKER)
    _marker_bundle(other, _ORIGINAL_MARKER)
    inner = other / "inner"
    inner.mkdir()
    (base / "link").symlink_to(inner, target_is_directory=True)
    supplied = base / "link" / ".." / "fixture-bundle.tar.gz"
    target = workspace.root / "bundle-path-semantics-target"
    target.mkdir()
    with step("Сохранить kernel-семантику archive path через symlink и parent"):
        result = run_restore_wrapper(
            wrapper,
            supplied,
            target,
            Path(sys.executable),
        )
        _check_restore_result(
            result, target, _ORIGINAL_MARKER, "archive path semantics"
        )


@reported(QH_N13)
def verify_valid_dependency_bundles(workspace: QualityWorkspace) -> None:
    with step("Проверить плоский payload"):
        flat = write_bundle(workspace.root / "bundle-valid-flat")
        findings = check_archive(flat)
        check_contains(
            "internal manifest is canonical, complete and valid",
            "\n".join(findings),
            "Результат проверки плоского bundle",
        )
        check_not_contains(
            "transactional restore contract",
            "\n".join(findings),
            "Verifier не заявляет непроверенную restore-семантику",
        )

    nested_files = regular_bundle_files(
        {
            "payload/SHA256SUMS": b"ordinary nested payload\n",
            "payload/bin/tool": b"nested executable payload\n",
            "payload/данные/кафé.txt": b"canonical UTF-8 payload\n",
        }
    )
    nested_manifest = canonical_manifest(nested_files)
    nested_manifest += checksum_record(
        file_digest(nested_files["payload/bin/tool"]),
        "./payload/bin/tool-copy",
    )
    nested_manifest += "\n"
    nested = write_bundle(
        workspace.root / "bundle-valid-nested",
        regular_files=nested_files,
        manifest_text=nested_manifest,
        extra_members=(
            ArchiveMember(
                f"{BUNDLE_ROOT}/tool-link",
                kind="symlink",
                linkname="payload/bin/tool",
            ),
            ArchiveMember(
                f"{BUNDLE_ROOT}/payload/bin/tool-copy",
                kind="hardlink",
                linkname=f"{BUNDLE_ROOT}/payload/bin/tool",
            ),
        ),
    )
    with step("Проверить вложенный payload и безопасные ссылки"):
        findings = check_archive(nested)
        check_equal(len(findings), 9, "Количество доказанных bundle-инвариантов")

    _verify_restore_snapshot_binding(workspace)
    _verify_wrapper_symlink_rejection(workspace)
    _verify_archive_path_semantics(workspace)


type ManifestCase = tuple[str, str, str]


def _manifest_grammar_cases(canonical: str) -> tuple[ManifestCase, ...]:
    first = canonical.splitlines()[0]
    first_digest, first_path = first.split("  ", 1)
    return (
        (
            "uppercase-digest",
            _replace_first_record(canonical, digest=first_digest.upper()),
            "64 lowercase hexadecimal",
        ),
        (
            "missing-separator",
            _replace_first_record(canonical, separator=" "),
            "exactly two spaces",
        ),
        (
            "empty-path",
            _replace_first_record(canonical, path=""),
            "target path is empty",
        ),
        (
            "missing-prefix",
            _replace_first_record(canonical, path=first_path.removeprefix("./")),
            "lacks canonical ./ prefix",
        ),
        (
            "absolute-path",
            _replace_first_record(canonical, path="/absolute/payload"),
            "target is absolute",
        ),
        (
            "backslash-path",
            _replace_first_record(canonical, path="./payload\\alias"),
            "contains a backslash",
        ),
        (
            "control-path",
            _replace_first_record(canonical, path="./payload\talias"),
            "forbidden Unicode character",
        ),
    )


def _manifest_path_cases(canonical: str) -> tuple[ManifestCase, ...]:
    first = canonical.splitlines()[0]
    first_digest, first_path = first.split("  ", 1)
    return (
        (
            "dot-component",
            _replace_first_record(canonical, path="./nested/./payload"),
            "is not canonical",
        ),
        (
            "parent-component",
            _replace_first_record(canonical, path="./nested/../payload"),
            "is not canonical",
        ),
        (
            "repeated-separator",
            _replace_first_record(canonical, path="./nested//payload"),
            "is not canonical",
        ),
        (
            "trailing-separator",
            _replace_first_record(canonical, path="./payload/"),
            "is not canonical",
        ),
        (
            "duplicate-target",
            canonical + first + "\n",
            "duplicate internal checksum target",
        ),
        (
            "canonical-duplicate-target",
            canonical
            + checksum_record(
                first_digest,
                f"./nested/../{first_path.removeprefix('./')}",
            )
            + "\n",
            "canonical duplicate internal checksum targets",
        ),
        (
            "self-reference",
            canonical + checksum_record("0" * 64, "./SHA256SUMS") + "\n",
            "must not hash itself",
        ),
    )


def _manifest_target_cases(canonical: str) -> tuple[ManifestCase, ...]:
    return (
        (
            "missing-target",
            canonical + checksum_record("0" * 64, "./missing.txt") + "\n",
            "target missing",
        ),
        (
            "checksum-mismatch",
            _replace_first_record(canonical, digest="0" * 64),
            "checksum mismatch",
        ),
    )


def _manifest_unicode_cases(canonical: str) -> tuple[ManifestCase, ...]:
    return (
        (
            "bidirectional-control",
            _replace_first_record(canonical, path="./payload\u202e.txt"),
            "forbidden Unicode character",
        ),
        (
            "non-nfc",
            _replace_first_record(canonical, path="./cafe\u0301.txt"),
            "not NFC-normalized",
        ),
        (
            "delete-control",
            _replace_first_record(canonical, path="./payload\x7f.txt"),
            "forbidden Unicode character",
        ),
    )


def _check_manifest_cases(
    workspace: QualityWorkspace,
    files: dict[str, bytes],
    cases: tuple[ManifestCase, ...],
) -> None:
    for case_id, manifest, expected in cases:
        with step(f"Отклонить manifest: {case_id}"):
            archive = write_bundle(
                workspace.root / f"bundle-manifest-{case_id}",
                regular_files=files,
                manifest_text=manifest,
            )
            _expect_rejected(
                archive,
                expected,
                f"Диагностика manifest-сценария {case_id}",
            )


def _check_manifest_completeness(
    workspace: QualityWorkspace,
    files: dict[str, bytes],
    canonical: str,
) -> None:
    unlisted_files = dict(files)
    unlisted_files["unlisted.txt"] = b"not in the manifest\n"
    unlisted = write_bundle(
        workspace.root / "bundle-manifest-unlisted",
        regular_files=unlisted_files,
        manifest_text=canonical,
    )
    with step("Отклонить неучтённый regular payload"):
        _expect_rejected(
            unlisted,
            "unlisted regular payload file",
            "Диагностика неучтённого payload",
        )


def _check_invalid_utf8_manifest(
    workspace: QualityWorkspace,
    files: dict[str, bytes],
    canonical: str,
) -> None:
    archive = write_bundle(
        workspace.root / "bundle-manifest-invalid-utf8",
        regular_files=files,
        manifest_bytes=canonical.encode("utf-8") + b"\xff",
    )
    with step("Отклонить manifest, который не является строгим UTF-8"):
        _expect_rejected(
            archive,
            "internal checksum manifest is not UTF-8",
            "Диагностика invalid UTF-8 manifest",
        )


def _check_manifest_nonregular_targets(
    workspace: QualityWorkspace,
    files: dict[str, bytes],
    canonical: str,
) -> None:
    symlink_manifest = canonical + checksum_record(
        file_digest(files["README.md"]),
        "./payload-link",
    )
    symlink_manifest += "\n"
    manifest_symlink = write_bundle(
        workspace.root / "bundle-manifest-symlink",
        regular_files=files,
        manifest_text=symlink_manifest,
        extra_members=(
            ArchiveMember(
                f"{BUNDLE_ROOT}/payload-link",
                kind="symlink",
                linkname="README.md",
            ),
        ),
    )
    with step("Отклонить symlink как checksum target"):
        _expect_rejected(
            manifest_symlink,
            "target is not a regular file",
            "Диагностика checksum target symlink",
        )

    directory_manifest = canonical + checksum_record(
        "0" * 64,
        "./payload-directory",
    )
    directory_manifest += "\n"
    manifest_directory = write_bundle(
        workspace.root / "bundle-manifest-directory",
        regular_files=files,
        manifest_text=directory_manifest,
        extra_members=(
            ArchiveMember(
                f"{BUNDLE_ROOT}/payload-directory",
                kind="directory",
                data=b"",
            ),
        ),
    )
    with step("Отклонить directory как checksum target"):
        _expect_rejected(
            manifest_directory,
            "target is not a regular file",
            "Диагностика checksum target directory",
        )


def _check_restore_entrypoint_mode(workspace: QualityWorkspace) -> None:
    archive = write_bundle(
        workspace.root / "bundle-restore-not-executable",
        regular_modes={"restore.sh": 0o644},
    )
    with step("Отклонить non-executable restore entrypoint"):
        _expect_rejected(
            archive,
            "restore.sh is not executable",
            "Диагностика режима restore entrypoint",
        )


@reported(QH_N14)
def verify_internal_manifest_rejections(workspace: QualityWorkspace) -> None:
    files = regular_bundle_files()
    canonical = canonical_manifest(files)
    _check_manifest_cases(workspace, files, _manifest_grammar_cases(canonical))
    _check_manifest_cases(workspace, files, _manifest_path_cases(canonical))
    _check_manifest_cases(workspace, files, _manifest_target_cases(canonical))
    _check_manifest_cases(workspace, files, _manifest_unicode_cases(canonical))
    _check_manifest_completeness(workspace, files, canonical)
    _check_invalid_utf8_manifest(workspace, files, canonical)
    _check_manifest_nonregular_targets(workspace, files, canonical)
    _check_restore_entrypoint_mode(workspace)


def _archive_case(
    workspace: QualityWorkspace,
    case_id: str,
    member: ArchiveMember,
) -> Path:
    return write_bundle(
        workspace.root / f"bundle-archive-{case_id}",
        extra_members=(member,),
    )


type ArchiveCase = tuple[str, ArchiveMember, str]


def _archive_path_cases() -> tuple[ArchiveCase, ...]:
    return (
        (
            "traversal",
            ArchiveMember(f"{BUNDLE_ROOT}/../escape"),
            "archive member path is not canonical",
        ),
        (
            "absolute",
            ArchiveMember("/absolute/payload"),
            "archive member path must be relative",
        ),
        (
            "alias",
            ArchiveMember(f"{BUNDLE_ROOT}/nested/../README.md"),
            "canonical duplicate archive members",
        ),
        (
            "repeated-separator",
            ArchiveMember(f"{BUNDLE_ROOT}//payload"),
            "archive member path is not canonical",
        ),
        (
            "duplicate",
            ArchiveMember(f"{BUNDLE_ROOT}/README.md"),
            "duplicate archive member",
        ),
        (
            "second-root",
            ArchiveMember("other-root/payload"),
            "one top-level root",
        ),
        (
            "bidirectional-control",
            ArchiveMember(f"{BUNDLE_ROOT}/payload\u202e.txt"),
            "forbidden Unicode character",
        ),
        (
            "non-nfc",
            ArchiveMember(f"{BUNDLE_ROOT}/cafe\u0301.txt"),
            "not NFC-normalized",
        ),
        (
            "invalid-utf8-surrogate",
            ArchiveMember(f"{BUNDLE_ROOT}/invalid\udcff.txt"),
            "not representable as UTF-8",
        ),
        (
            "delete-control",
            ArchiveMember(f"{BUNDLE_ROOT}/delete\x7f.txt"),
            "forbidden Unicode character",
        ),
    )


def _archive_link_and_metadata_cases() -> tuple[ArchiveCase, ...]:
    return (
        (
            "escaping-symlink",
            ArchiveMember(
                f"{BUNDLE_ROOT}/payload/link",
                kind="symlink",
                linkname="../../../outside",
            ),
            "escaping symlink",
        ),
        (
            "escaping-hardlink",
            ArchiveMember(
                f"{BUNDLE_ROOT}/payload/hardlink",
                kind="hardlink",
                linkname="outside",
            ),
            "escaping hardlink",
        ),
        (
            "hardlink-dot-alias",
            ArchiveMember(
                f"{BUNDLE_ROOT}/payload/hardlink-dot",
                kind="hardlink",
                linkname=f"{BUNDLE_ROOT}/./README.md",
            ),
            "hardlink target is not canonical",
        ),
        (
            "hardlink-parent-alias",
            ArchiveMember(
                f"{BUNDLE_ROOT}/payload/hardlink-parent",
                kind="hardlink",
                linkname=f"{BUNDLE_ROOT}/payload/../README.md",
            ),
            "hardlink target is not canonical",
        ),
        (
            "hardlink-repeated-separator",
            ArchiveMember(
                f"{BUNDLE_ROOT}/payload/hardlink-repeated",
                kind="hardlink",
                linkname=f"{BUNDLE_ROOT}//README.md",
            ),
            "hardlink target is not canonical",
        ),
        (
            "hardlink-trailing-separator",
            ArchiveMember(
                f"{BUNDLE_ROOT}/payload/hardlink-trailing",
                kind="hardlink",
                linkname=f"{BUNDLE_ROOT}/README.md/",
            ),
            "hardlink target is not canonical",
        ),
        (
            "owner",
            ArchiveMember(f"{BUNDLE_ROOT}/owned", uid=1000),
            "non-normalized numeric owner",
        ),
        (
            "special-file",
            ArchiveMember(f"{BUNDLE_ROOT}/pipe", kind="fifo"),
            "unsupported archive member type",
        ),
    )


def _check_archive_cases(
    workspace: QualityWorkspace,
    cases: tuple[ArchiveCase, ...],
) -> None:
    for case_id, member, expected in cases:
        with step(f"Отклонить tar-топологию: {case_id}"):
            archive = _archive_case(workspace, case_id, member)
            _expect_rejected(
                archive,
                expected,
                f"Диагностика tar-сценария {case_id}",
            )


def _check_archive_ancestor_cases(workspace: QualityWorkspace) -> None:
    symlink_ancestor = write_bundle(
        workspace.root / "bundle-archive-symlink-ancestor",
        extra_members=(
            ArchiveMember(
                f"{BUNDLE_ROOT}/alias",
                kind="symlink",
                linkname="payload",
            ),
            ArchiveMember(f"{BUNDLE_ROOT}/alias/nested"),
        ),
    )
    with step("Отклонить member под symlink-предком"):
        _expect_rejected(
            symlink_ancestor,
            "descends through a symlink",
            "Диагностика symlink-предка",
        )

    regular_ancestor = write_bundle(
        workspace.root / "bundle-archive-regular-ancestor",
        extra_members=(
            ArchiveMember(f"{BUNDLE_ROOT}/regular-ancestor"),
            ArchiveMember(f"{BUNDLE_ROOT}/regular-ancestor/nested"),
        ),
    )
    with step("Отклонить member под regular-файлом"):
        _expect_rejected(
            regular_ancestor,
            "descends through a non-directory",
            "Диагностика regular-предка",
        )


def _unexpected_tarfile_open(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("tarfile.open reached before metadata preflight")


def _check_archive_size_quotas(archive: Path) -> None:
    cases = (
        (
            "archive-bytes",
            "MAX_ARCHIVE_BYTES",
            archive.stat().st_size - 1,
            "archive exceeds",
        ),
        ("checksum-bytes", "MAX_CHECKSUM_BYTES", 8, "detached checksum exceeds"),
        ("member-count", "MAX_ARCHIVE_MEMBERS", 1, "archive exceeds 1 members"),
        (
            "member-bytes",
            "MAX_ARCHIVE_MEMBER_BYTES",
            1,
            "archive member exceeds 1 bytes",
        ),
        (
            "aggregate-bytes",
            "MAX_ARCHIVE_EXTRACTED_BYTES",
            1,
            "archive regular payload exceeds 1 bytes",
        ),
        (
            "tar-bytes",
            "MAX_ARCHIVE_TAR_BYTES",
            512,
            "uncompressed tar exceeds 512 bytes",
        ),
    )
    for case_id, attribute, limit, expected in cases:
        with (
            step(f"Отклонить превышение resource quota: {case_id}"),
            pytest.MonkeyPatch.context() as scoped,
        ):
            scoped.setattr(verifier_module, attribute, limit)
            _expect_rejected(archive, expected, f"Диагностика quota {case_id}")


def _check_archive_metadata_quotas(workspace: QualityWorkspace) -> None:
    long_path = f"{BUNDLE_ROOT}/{'x' * 160}"
    path_archive = write_bundle(
        workspace.root / "bundle-resource-path",
        extra_members=(ArchiveMember(long_path),),
        archive_format=tarfile.GNU_FORMAT,
    )
    with (
        step("Отклонить GNU metadata до передачи archive в tarfile"),
        pytest.MonkeyPatch.context() as scoped,
    ):
        scoped.setattr(verifier_module, "MAX_ARCHIVE_EXTENSION_BYTES", 8)
        scoped.setattr(
            "tools.platform.dependency_bundles.verify_bundle.tarfile.open",
            _unexpected_tarfile_open,
        )
        _expect_rejected(
            path_archive,
            "archive extension header exceeds 8 bytes",
            "Диагностика pre-tarfile metadata quota",
        )

    unsafe_metadata_archives = (
        (
            write_bundle(
                workspace.root / "bundle-resource-global-pax",
                pax_headers={"comment": "global metadata must not amplify"},
                archive_format=tarfile.PAX_FORMAT,
            ),
            "PAX archive headers are unsupported",
            "global PAX",
        ),
        (
            write_bundle(
                workspace.root / "bundle-resource-pax-sparse",
                extra_members=(
                    ArchiveMember(
                        f"{BUNDLE_ROOT}/sparse-fixture",
                        data=b"x",
                        pax_headers={
                            "GNU.sparse.map": "0,1",
                            "GNU.sparse.size": "1",
                        },
                    ),
                ),
                archive_format=tarfile.PAX_FORMAT,
            ),
            "PAX archive headers are unsupported",
            "PAX sparse",
        ),
    )
    for unsafe_archive, expected, label in unsafe_metadata_archives:
        with (
            step(f"Отклонить pre-yield metadata amplification: {label}"),
            pytest.MonkeyPatch.context() as scoped,
        ):
            scoped.setattr(
                "tools.platform.dependency_bundles.verify_bundle.tarfile.open",
                _unexpected_tarfile_open,
            )
            _expect_rejected(unsafe_archive, expected, label)
    with (
        step("Отклонить чрезмерную длину archive member path"),
        pytest.MonkeyPatch.context() as scoped,
    ):
        scoped.setattr(verifier_module, "MAX_ARCHIVE_MEMBER_PATH_BYTES", 128)
        _expect_rejected(
            path_archive,
            "path or link target exceeds 128 bytes",
            "Диагностика path quota",
        )


def _check_archive_manifest_quota(workspace: QualityWorkspace, archive: Path) -> None:
    extraction = workspace.root / "bundle-resource-manifest-extraction"
    extraction.mkdir()
    with (
        step("Отклонить большой manifest до записи extraction tree"),
        pytest.MonkeyPatch.context() as scoped,
    ):
        scoped.setattr(verifier_module, "MAX_INTERNAL_MANIFEST_BYTES", 1)
        with pytest.raises(AssertionError) as captured:
            check_archive(archive, extract_to=extraction)
        check_contains(
            "internal checksum manifest exceeds 1 bytes",
            str(captured.value),
            "Диагностика pre-extraction manifest quota",
        )
        check_equal(tuple(extraction.iterdir()), (), "pre-extraction destination")


def _check_archive_resource_limits(workspace: QualityWorkspace) -> None:
    archive = write_bundle(workspace.root / "bundle-resource-limits")
    _check_archive_size_quotas(archive)
    _check_archive_metadata_quotas(workspace)
    _check_archive_manifest_quota(workspace, archive)


@reported(QH_N15)
def verify_archive_topology_rejections(workspace: QualityWorkspace) -> None:
    _check_archive_cases(workspace, _archive_path_cases())
    _check_archive_cases(workspace, _archive_link_and_metadata_cases())
    _check_archive_ancestor_cases(workspace)
    _check_archive_resource_limits(workspace)


@reported(QH_N16)
def verify_detached_checksum_rejections(workspace: QualityWorkspace) -> None:
    def uppercase(archive: Path) -> None:
        write_detached_checksum(
            archive,
            digest=file_digest(archive.read_bytes()).upper(),
        )

    def one_space(archive: Path) -> None:
        write_detached_checksum(archive, separator=" ")

    def mismatched_name(archive: Path) -> None:
        write_detached_checksum(archive, name="other.tar.gz")

    def path_name(archive: Path) -> None:
        write_detached_checksum(archive, name=f"nested/{archive.name}")

    def mismatched_digest(archive: Path) -> None:
        write_detached_checksum(archive, digest="0" * 64)

    def multiple_records(archive: Path) -> None:
        write_detached_checksum(
            archive,
            suffix=f"\n{'0' * 64}  {archive.name}\n",
        )

    def symlinked_checksum(archive: Path) -> None:
        checksum = archive.with_name(archive.name + ".sha256")
        regular = checksum.with_name(checksum.name + ".regular")
        checksum.replace(regular)
        checksum.symlink_to(regular.name)

    def symlinked_archive(archive: Path) -> None:
        regular = archive.with_name("regular-bundle.tar.gz")
        archive.replace(regular)
        archive.symlink_to(regular.name)

    cases: tuple[tuple[str, Callable[[Path], None], str], ...] = (
        ("uppercase-digest", uppercase, "64 lowercase hexadecimal"),
        ("missing-separator", one_space, "exactly two spaces"),
        ("basename-mismatch", mismatched_name, "basename mismatch"),
        ("path-name", path_name, "contains a path"),
        ("digest-mismatch", mismatched_digest, "detached checksum mismatch"),
        ("multiple-records", multiple_records, "exactly one checksum record"),
        ("symlink-checksum", symlinked_checksum, "detached .sha256 missing, unsafe"),
        ("symlink-archive", symlinked_archive, "archive missing, unsafe"),
    )
    for case_id, mutate, expected in cases:
        with step(f"Отклонить detached checksum: {case_id}"):
            archive = write_bundle(workspace.root / f"bundle-detached-{case_id}")
            mutate(archive)
            _expect_rejected(
                archive,
                expected,
                f"Диагностика detached-сценария {case_id}",
            )

    _check_nonregular_bundle_sources(workspace)


def _check_nonregular_bundle_sources(workspace: QualityWorkspace) -> None:
    def fifo_archive(archive: Path) -> None:
        archive.unlink()
        os.mkfifo(archive)

    def fifo_checksum(archive: Path) -> None:
        checksum = archive.with_name(archive.name + ".sha256")
        checksum.unlink()
        os.mkfifo(checksum)

    cases: tuple[tuple[str, Callable[[Path], None], str], ...] = (
        ("fifo-archive", fifo_archive, "archive is not a regular file"),
        ("fifo-checksum", fifo_checksum, "detached .sha256 is not a regular file"),
    )
    for case_id, mutate, expected in cases:
        with step(f"Отклонить non-regular источник без блокировки: {case_id}"):
            archive = write_bundle(workspace.root / f"bundle-detached-{case_id}")
            mutate(archive)
            _expect_cli_rejected(archive, expected, f"Диагностика {case_id}")
