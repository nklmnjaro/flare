from pathlib import Path

from tools.quality.tests.local_execution.process_scenarios import (
    verify_process_descendant_rejection,
    verify_process_output_limit,
    verify_process_python_isolation,
    verify_process_timeout_tree_cleanup,
)


def test_process_output_limit(tmp_path: Path) -> None:
    verify_process_output_limit(tmp_path)


def test_process_timeout_tree_cleanup(tmp_path: Path) -> None:
    verify_process_timeout_tree_cleanup(tmp_path)


def test_process_descendant_rejection(tmp_path: Path) -> None:
    verify_process_descendant_rejection(tmp_path)


def test_process_python_isolation(tmp_path: Path) -> None:
    verify_process_python_isolation(tmp_path)
