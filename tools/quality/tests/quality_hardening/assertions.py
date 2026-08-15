from __future__ import annotations

from collections.abc import Collection

from tools.local_execution.model import ProcessResult
from tools.quality.tests.quality_hardening.reporting import comparison

_MAX_VALUE_CHARS = 180


def _render[T](value: T) -> str:
    rendered = repr(value)
    if len(rendered) <= _MAX_VALUE_CHARS:
        return rendered
    omitted = len(rendered) - _MAX_VALUE_CHARS
    return f"{rendered[:_MAX_VALUE_CHARS]}…[{omitted} символов скрыто]"


def check_equal[T](actual: T, expected: T, label: str) -> None:
    with comparison(
        label,
        expected=_render(expected),
        actual=_render(actual),
    ):
        if actual != expected:
            raise AssertionError(
                f"{label}: ожидалось {_render(expected)}, получено {_render(actual)}"
            )


def check_contains(needle: str, value: str, label: str) -> None:
    observed = needle in value
    with comparison(label, expected=f"содержит {needle!r}", actual=_render(observed)):
        if not observed:
            raise AssertionError(f"{label}: ожидалось наличие {needle!r}")


def check_not_contains(needle: str, value: str, label: str) -> None:
    observed = needle not in value
    with comparison(
        label, expected=f"не содержит {needle!r}", actual=_render(observed)
    ):
        if not observed:
            raise AssertionError(f"{label}: ожидалось отсутствие {needle!r}")


def check_process(
    result: ProcessResult,
    expected_exit: int,
    label: str,
) -> None:
    check_equal(result.returncode, expected_exit, f"{label}: код завершения")


def check_rule_set(
    actual: Collection[str],
    expected: Collection[str],
    label: str,
) -> None:
    check_equal(frozenset(actual), frozenset(expected), label)
