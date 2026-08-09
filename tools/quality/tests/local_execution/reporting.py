from collections.abc import Callable
from functools import wraps

import allure

from tools.quality.tests.project_state.reporting import attach_text, step_context


def scenario[**P](
    scenario_id: str,
    title: str,
) -> Callable[[Callable[P, None]], Callable[P, None]]:
    def decorate(operation: Callable[P, None]) -> Callable[P, None]:
        @wraps(operation)
        def reported(*args: P.args, **kwargs: P.kwargs) -> None:
            allure.dynamic.label("scenario_id", scenario_id)
            allure.dynamic.tag("local-first", "contract")
            with step_context(title):
                operation(*args, **kwargs)

        return reported

    return decorate


__all__ = ["attach_text", "scenario", "step_context"]
