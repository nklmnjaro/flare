from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from types import CoroutineType
from typing import Protocol, TypeIs, overload

import allure

_MAX_REPORTED_CHARS = 240


@dataclass(frozen=True, slots=True)
class ScenarioMetadata:
    scenario_id: str
    title: str
    feature: str

    @property
    def report_title(self) -> str:
        return f"[{self.scenario_id}] {self.title}"


def scenario_title[**P, R](
    metadata: ScenarioMetadata,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorate(operation: Callable[P, R]) -> Callable[P, R]:
        return allure.title(metadata.report_title)(operation)

    return decorate


def fixture_title[**P, R](
    title: str,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorate(operation: Callable[P, R]) -> Callable[P, R]:
        return allure.title(title)(operation)

    return decorate


def _bounded(value: str) -> str:
    if len(value) <= _MAX_REPORTED_CHARS:
        return value
    omitted = len(value) - _MAX_REPORTED_CHARS
    return f"{value[:_MAX_REPORTED_CHARS]}…[{omitted} символов скрыто]"


@contextmanager
def step(title: str) -> Iterator[None]:
    with allure.step(_bounded(title)):
        yield


@contextmanager
def comparison(
    label: str,
    *,
    expected: str,
    actual: str,
) -> Iterator[None]:
    title = f"{label}: ожидалось {expected}; получено {actual}"
    with step(title):
        yield


@contextmanager
def _scenario(metadata: ScenarioMetadata) -> Iterator[None]:
    allure.dynamic.parent_suite("Инженерные контракты Flare")
    allure.dynamic.suite("Укрепление качества")
    allure.dynamic.feature(metadata.feature)
    allure.dynamic.label("scenario_id", metadata.scenario_id)
    allure.dynamic.tag("quality-hardening", "contract")
    with step(metadata.title):
        yield


class _AsyncOperation[**P, R](Protocol):
    async def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R: ...


class _OperationClassifier[**P, A, S]:
    @staticmethod
    def is_async(
        operation: _AsyncOperation[P, A] | Callable[P, S],
    ) -> TypeIs[_AsyncOperation[P, A]]:
        return inspect.iscoroutinefunction(operation) or inspect.iscoroutinefunction(
            type(operation).__call__
        )


class _Reported:
    def __init__(self, metadata: ScenarioMetadata) -> None:
        self._metadata = metadata

    @overload
    def __call__[**P, R](
        self,
        operation: _AsyncOperation[P, R],
    ) -> _AsyncOperation[P, R]: ...

    @overload
    def __call__[**P, R](
        self,
        operation: Callable[P, R],
    ) -> Callable[P, R]: ...

    def __call__[**P, R, A](
        self,
        operation: _AsyncOperation[P, A] | Callable[P, R],
    ) -> _AsyncOperation[P, A] | Callable[P, R]:
        classifier: _OperationClassifier[P, A, R] = _OperationClassifier()
        if classifier.is_async(operation):

            @wraps(operation)
            async def execute_async(*args: P.args, **kwargs: P.kwargs) -> A:
                with _scenario(self._metadata):
                    return await operation(*args, **kwargs)

            return execute_async

        @wraps(operation)
        def execute(*args: P.args, **kwargs: P.kwargs) -> R:
            with _scenario(self._metadata):
                result = operation(*args, **kwargs)
                if inspect.isawaitable(result):
                    if isinstance(result, CoroutineType):
                        result.close()
                    raise TypeError(
                        "Синхронная операция вернула awaitable; используйте async def"
                    )
                return result

        return execute


def reported(metadata: ScenarioMetadata) -> _Reported:
    return _Reported(metadata)
