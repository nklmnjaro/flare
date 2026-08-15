from __future__ import annotations

import asyncio
import inspect
import warnings
from collections.abc import Coroutine, Iterator
from contextlib import contextmanager

import pytest

from tools.quality.tests.quality_hardening import reporting
from tools.quality.tests.quality_hardening.assertions import check_equal
from tools.quality.tests.quality_hardening.reporting import reported, step
from tools.quality.tests.quality_hardening.scenario_catalog import QH_N12


def _verify_sync_operation() -> None:
    calls = 0

    @reported(QH_N12)
    def operation(value: int) -> int:
        nonlocal calls
        calls += 1
        return value

    with step("Проверить однократное синхронное выполнение и результат"):
        check_equal(operation(17), 17, "результат синхронной операции")
        check_equal(calls, 1, "число синхронных выполнений")


def _verify_async_operation() -> None:
    calls = 0

    @reported(QH_N12)
    async def operation(value: int) -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return value

    with step("Проверить признак coroutine function и однократное ожидание"):
        check_equal(
            inspect.iscoroutinefunction(operation),
            True,
            "признак асинхронной операции",
        )
        with warnings.catch_warnings(record=True) as observed_warnings:
            warnings.simplefilter("always")
            result = asyncio.run(operation(23))
        runtime_warnings = tuple(
            warning
            for warning in observed_warnings
            if issubclass(warning.category, RuntimeWarning)
        )
        check_equal(result, 23, "результат асинхронной операции")
        check_equal(calls, 1, "число асинхронных выполнений")
        check_equal(runtime_warnings, (), "предупреждения RuntimeWarning")


def _verify_async_callable() -> None:
    class AsyncCallable:
        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, value: int) -> int:
            self.calls += 1
            await asyncio.sleep(0)
            return value

    target = AsyncCallable()
    operation = reported(QH_N12)(target)
    with step("Сохранить async-семантику вызываемого объекта"):
        check_equal(
            inspect.iscoroutinefunction(operation),
            True,
            "признак асинхронного вызываемого объекта",
        )
        check_equal(asyncio.run(operation(29)), 29, "результат вызываемого объекта")
        check_equal(target.calls, 1, "число выполнений вызываемого объекта")


def _verify_sync_coroutine_factory_fails_fast() -> None:
    async def deferred(value: int) -> int:
        await asyncio.sleep(0)
        return value

    @reported(QH_N12)
    def operation(value: int) -> Coroutine[None, None, int]:
        return deferred(value)

    with step("Отклонить синхронную фабрику coroutine без утечки warning"):
        with warnings.catch_warnings(record=True) as observed_warnings:
            warnings.simplefilter("always")
            with pytest.raises(TypeError, match="используйте async def"):
                _ = operation(31)
        runtime_warnings = tuple(
            warning
            for warning in observed_warnings
            if issubclass(warning.category, RuntimeWarning)
        )
        check_equal(runtime_warnings, (), "предупреждения фабрики coroutine")


def _verify_exception_identity() -> None:
    sync_error = ValueError("синхронная ошибка")
    async_error = RuntimeError("асинхронная ошибка")

    @reported(QH_N12)
    def failing_sync() -> None:
        raise sync_error

    @reported(QH_N12)
    async def failing_async() -> None:
        await asyncio.sleep(0)
        raise async_error

    with step("Сохранить исходные исключения без замены"):
        observed_sync_error: ValueError | None = None
        observed_async_error: RuntimeError | None = None
        try:
            failing_sync()
        except ValueError as error:
            observed_sync_error = error
        try:
            asyncio.run(failing_async())
        except RuntimeError as error:
            observed_async_error = error
        check_equal(
            observed_sync_error is sync_error,
            True,
            "идентичность синхронного исключения",
        )
        check_equal(
            observed_async_error is async_error,
            True,
            "идентичность асинхронного исключения",
        )


@reported(QH_N12)
def verify_sync_and_async_reporting(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    @contextmanager
    def observed_scenario(metadata: reporting.ScenarioMetadata) -> Iterator[None]:
        events.append(f"вход:{metadata.scenario_id}")
        try:
            yield
        finally:
            events.append(f"выход:{metadata.scenario_id}")

    monkeypatch.setattr(reporting, "_scenario", observed_scenario)
    _verify_sync_operation()
    _verify_async_operation()
    _verify_async_callable()
    _verify_sync_coroutine_factory_fails_fast()
    _verify_exception_identity()
    with step("Проверить отчётный контекст каждого вызова"):
        check_equal(
            events,
            [
                "вход:QH-N12",
                "выход:QH-N12",
                "вход:QH-N12",
                "выход:QH-N12",
                "вход:QH-N12",
                "выход:QH-N12",
                "вход:QH-N12",
                "выход:QH-N12",
                "вход:QH-N12",
                "выход:QH-N12",
                "вход:QH-N12",
                "выход:QH-N12",
            ],
            "последовательность отчётных событий",
        )
