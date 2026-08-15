from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tools.quality.tests.local_execution.assertions import (
    assert_equal,
    assert_false,
)
from tools.quality.tests.local_execution.reporting import scenario

SOURCE_ROOT = Path(__file__).resolve().parents[4]
_DIRECT_EXECUTION_TOKEN = ".venv" + "/bin/"
_EVIDENCE = (
    SOURCE_ROOT
    / "tools/quality/tests/local_execution/stage0_evidence"
    / "DIRECT_ENV_EXECUTION_INVENTORY.json"
)
_EXCLUDED_DIRECTORIES = {
    ".git",
    ".cache",
    ".tmp",
    ".venv",
    ".flare",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}
_TOP_LEVEL_KEYS = {
    "mechanical_scan",
    "occurrences",
    "public_bypass_count",
    "schema_version",
}
_OCCURRENCE_KEYS = {
    "classification",
    "column",
    "line",
    "path",
    "public_bypass",
    "text",
}

type JSONValue = None | bool | int | str | list[JSONValue] | dict[str, JSONValue]
type PhysicalOccurrence = tuple[str, int, int, str]
type DeclaredOccurrence = tuple[str, int, int, str, str, bool]


class InventoryError(AssertionError):
    pass


def _reject_number(value: str) -> int:
    raise InventoryError(f"non-integer inventory number is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, JSONValue]]) -> dict[str, JSONValue]:
    result: dict[str, JSONValue] = {}
    for key, value in pairs:
        if key in result:
            raise InventoryError(f"duplicate inventory key is forbidden: {key}")
        result[key] = value
    return result


def _load_inventory(path: Path) -> JSONValue:
    try:
        value: JSONValue = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise InventoryError("inventory is not strict UTF-8 JSON") from error
    return value


def _mapping(value: JSONValue, label: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise InventoryError(f"{label} must be a mapping")
    return value


def _required_string(item: dict[str, JSONValue], key: str) -> str:
    value = item[key]
    if not isinstance(value, str) or not value:
        raise InventoryError(f"inventory {key} must be a nonempty string")
    return value


def _positive_integer(item: dict[str, JSONValue], key: str) -> int:
    value = item[key]
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise InventoryError(f"inventory {key} must be a positive integer")
    return value


def _declared_occurrence(value: JSONValue) -> DeclaredOccurrence:
    item = _mapping(value, "inventory occurrence")
    if set(item) != _OCCURRENCE_KEYS:
        raise InventoryError("inventory occurrence schema is invalid")
    bypass = item["public_bypass"]
    if not isinstance(bypass, bool):
        raise InventoryError("inventory public_bypass must be a boolean")
    return (
        _required_string(item, "path"),
        _positive_integer(item, "line"),
        _positive_integer(item, "column"),
        _required_string(item, "text"),
        _required_string(item, "classification"),
        bypass,
    )


def _declared_inventory(path: Path) -> tuple[list[DeclaredOccurrence], int]:
    mapping = _mapping(_load_inventory(path), "inventory")
    if set(mapping) != _TOP_LEVEL_KEYS:
        raise InventoryError("inventory top-level schema is invalid")
    if mapping["schema_version"] != "1.0":
        raise InventoryError("inventory schema_version must be 1.0")
    _required_string(mapping, "mechanical_scan")
    raw_occurrences = mapping["occurrences"]
    if not isinstance(raw_occurrences, list):
        raise InventoryError("inventory occurrences must be a list")
    occurrences = sorted(_declared_occurrence(item) for item in raw_occurrences)
    bypass_count = mapping["public_bypass_count"]
    if (
        not isinstance(bypass_count, int)
        or isinstance(bypass_count, bool)
        or bypass_count < 0
    ):
        raise InventoryError("inventory public_bypass_count must be an integer")
    return occurrences, bypass_count


def _scan_occurrences(source_root: Path, evidence: Path) -> list[PhysicalOccurrence]:
    occurrences: list[PhysicalOccurrence] = []
    for directory, names, files in os.walk(source_root, topdown=True):
        names[:] = sorted(name for name in names if name not in _EXCLUDED_DIRECTORIES)
        for name in sorted(files):
            path = Path(directory, name)
            if path == evidence:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeError:
                continue
            relative = path.relative_to(source_root).as_posix()
            for line_number, text in enumerate(lines, start=1):
                offset = 0
                while (index := text.find(_DIRECT_EXECUTION_TOKEN, offset)) >= 0:
                    occurrences.append((relative, line_number, index + 1, text))
                    offset = index + 1
    return sorted(occurrences)


def _verify_inventory(source_root: Path, evidence: Path) -> None:
    declared, bypass_count = _declared_inventory(evidence)
    physical = [
        (path, line, column, text) for path, line, column, text, _, _ in declared
    ]
    assert_equal(len(set(physical)), len(physical), "unique declared occurrences")
    assert_equal(_scan_occurrences(source_root, evidence), physical, "inventory scan")
    bypasses = [bypass for *_, bypass in declared]
    assert_false(any(bypasses), "classified direct public bypass")
    assert_equal(bypass_count, sum(bypasses), "public bypass count")


def _write_fixture(fixture: Path) -> tuple[Path, Path, str]:
    fixture.mkdir()
    source = fixture / "declared.py"
    line = f'PYTHON = "{_DIRECT_EXECUTION_TOKEN}python"'
    source.write_text(line + "\n", encoding="utf-8")
    evidence = fixture / "inventory.json"
    evidence.write_text(
        json.dumps(
            {
                "mechanical_scan": "fixture",
                "occurrences": [
                    {
                        "classification": "declared fixture",
                        "column": line.index(_DIRECT_EXECUTION_TOKEN) + 1,
                        "line": 1,
                        "path": "declared.py",
                        "public_bypass": False,
                        "text": line,
                    }
                ],
                "public_bypass_count": 0,
                "schema_version": "1.0",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return source, evidence, line


@scenario("A-016", "Inventory every direct project-environment execution")
def verify_direct_execution_inventory(tmp_path: Path) -> None:
    _verify_inventory(SOURCE_ROOT, _EVIDENCE)
    source, evidence, line = _write_fixture(tmp_path / "inventory-occurrences")
    _verify_inventory(source.parent, evidence)

    source.write_text(line + "\n" + line + "\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="inventory scan"):
        _verify_inventory(source.parent, evidence)

    source.write_text(line + "\n", encoding="utf-8")
    raw = evidence.read_text(encoding="utf-8")
    duplicate = raw.replace(
        '"public_bypass": false',
        '"public_bypass": true, "public_bypass": false',
        1,
    )
    evidence.write_text(duplicate, encoding="utf-8")
    with pytest.raises(InventoryError, match="duplicate inventory key"):
        _verify_inventory(source.parent, evidence)
