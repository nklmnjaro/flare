from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps

import allure

from tools.quality.tests.project_state.reporting import attach_text, step_context


@dataclass(frozen=True, slots=True)
class ScenarioMetadata:
    scenario_id: str
    title: str
    feature: str | None


def reported[**P](
    metadata: ScenarioMetadata,
) -> Callable[[Callable[P, None]], Callable[P, None]]:
    def decorate(operation: Callable[P, None]) -> Callable[P, None]:
        @wraps(operation)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> None:
            if metadata.feature is not None:
                allure.dynamic.parent_suite("Инженерные контракты Flare")
                allure.dynamic.suite("Локальное выполнение")
                allure.dynamic.feature(metadata.feature)
                allure.dynamic.title(f"[{metadata.scenario_id}] {metadata.title}")
            allure.dynamic.label("scenario_id", metadata.scenario_id)
            allure.dynamic.tag("local-first", "contract")
            with step_context(metadata.title):
                operation(*args, **kwargs)

        return wrapped

    return decorate


def scenario[**P](
    scenario_id: str,
    title: str,
    *,
    feature: str | None = None,
) -> Callable[[Callable[P, None]], Callable[P, None]]:
    return reported(ScenarioMetadata(scenario_id, title, feature))


__all__ = [
    "ScenarioMetadata",
    "attach_text",
    "reported",
    "scenario",
    "step_context",
]
