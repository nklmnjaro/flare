from pathlib import Path

import pytest

from tools.quality.tests.local_execution.clean_room_retention_safety_scenarios import (
    verify_bounded_retention_membership,
    verify_nested_device_retention_guard,
    verify_proof_size_preflight,
    verify_source_manifest_size_preflight,
)
from tools.quality.tests.local_execution.clean_room_scenarios import (
    verify_atomic_proof_crash_states,
    verify_fifo_evidence_is_bounded,
    verify_post_publication_invariants,
    verify_public_clean_room_integration,
    verify_public_descendant_rejection,
    verify_public_transient_replacement_rejection,
    verify_retention_attack_resistance,
    verify_retention_failure_diagnostics,
    verify_retention_membership_and_modes,
    verify_retention_success_and_preflight,
    verify_source_discovery_pruning,
)


def test_atomic_proof_crash_states(tmp_path: Path) -> None:
    verify_atomic_proof_crash_states(tmp_path)


def test_retention_success_and_preflight(tmp_path: Path) -> None:
    verify_retention_success_and_preflight(tmp_path)


def test_retention_membership_and_modes(tmp_path: Path) -> None:
    verify_retention_membership_and_modes(tmp_path)


def test_nested_device_retention_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_nested_device_retention_guard(tmp_path, monkeypatch)


def test_bounded_retention_membership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_bounded_retention_membership(tmp_path, monkeypatch)


def test_proof_size_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_proof_size_preflight(tmp_path, monkeypatch)


def test_source_manifest_size_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_source_manifest_size_preflight(tmp_path, monkeypatch)


def test_fifo_evidence_is_bounded(tmp_path: Path) -> None:
    verify_fifo_evidence_is_bounded(tmp_path)


def test_retention_attack_resistance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_retention_attack_resistance(tmp_path, monkeypatch)


def test_retention_failure_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_retention_failure_diagnostics(tmp_path, monkeypatch)


def test_post_publication_invariants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_post_publication_invariants(tmp_path, monkeypatch)


def test_source_discovery_pruning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_source_discovery_pruning(tmp_path, monkeypatch)


def test_public_clean_room_integration(tmp_path: Path) -> None:
    verify_public_clean_room_integration(tmp_path)


def test_public_descendant_rejection(tmp_path: Path) -> None:
    verify_public_descendant_rejection(tmp_path)


def test_public_transient_replacement_rejection(tmp_path: Path) -> None:
    verify_public_transient_replacement_rejection(tmp_path)
