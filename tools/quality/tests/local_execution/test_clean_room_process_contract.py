from pathlib import Path

import pytest

from tools.quality.tests.local_execution.clean_room_process_scenarios import (
    verify_client_finalizers_after_signal_error,
    verify_final_rescan_failure_cleanup,
    verify_parent_interruption_cleanup,
    verify_partial_descendant_scan_cleanup,
    verify_post_stop_interruption_cleanup,
    verify_public_process_output_limit,
    verify_reparented_descendant_fallback,
    verify_shared_cleanup_deadline,
    verify_source_supervisor_finalizers,
    verify_stopped_supervisor_fallback,
    verify_supervisor_capture_failure_cleanup,
    verify_threaded_descendant_fallback,
)


def test_public_process_output_limit(tmp_path: Path) -> None:
    verify_public_process_output_limit(tmp_path)


def test_supervisor_capture_failure_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_supervisor_capture_failure_cleanup(tmp_path, monkeypatch)


def test_parent_interruption_cleanup(tmp_path: Path) -> None:
    verify_parent_interruption_cleanup(tmp_path)


def test_stopped_supervisor_fallback(tmp_path: Path) -> None:
    verify_stopped_supervisor_fallback(tmp_path)


def test_threaded_descendant_fallback(tmp_path: Path) -> None:
    verify_threaded_descendant_fallback(tmp_path)


def test_reparented_descendant_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_reparented_descendant_fallback(tmp_path, monkeypatch)


def test_final_rescan_failure_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_final_rescan_failure_cleanup(tmp_path, monkeypatch)


def test_partial_descendant_scan_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_partial_descendant_scan_cleanup(tmp_path, monkeypatch)


def test_post_stop_interruption_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_post_stop_interruption_cleanup(tmp_path, monkeypatch)


def test_shared_cleanup_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    verify_shared_cleanup_deadline(monkeypatch)


def test_source_supervisor_finalizers(monkeypatch: pytest.MonkeyPatch) -> None:
    verify_source_supervisor_finalizers(monkeypatch)


def test_client_finalizers_after_signal_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_client_finalizers_after_signal_error(tmp_path, monkeypatch)
