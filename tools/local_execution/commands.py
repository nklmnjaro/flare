from collections.abc import Callable, Sequence

from tools.local_execution.capabilities import (
    check,
    check_fast,
    diagnose,
    doctor,
    quality_advisory,
    state_allure,
    state_allure_open,
    state_check,
    state_static,
    state_test,
    verify,
)
from tools.local_execution.model import Capability
from tools.local_execution.process import CommandContext, ProcessRunner, run_process

type CapabilityHandler = Callable[[CommandContext, ProcessRunner], int]

HANDLER_PAIRS: tuple[tuple[Capability, CapabilityHandler], ...] = (
    (Capability.DOCTOR, doctor),
    (Capability.CHECK_FAST, check_fast),
    (Capability.CHECK, check),
    (Capability.VERIFY, verify),
    (Capability.QUALITY_ADVISORY, quality_advisory),
    (Capability.DIAGNOSE, diagnose),
    (Capability.STATE_CHECK, state_check),
    (Capability.STATE_STATIC, state_static),
    (Capability.STATE_TEST, state_test),
    (Capability.STATE_ALLURE, state_allure),
    (Capability.STATE_ALLURE_OPEN, state_allure_open),
)


def build_dispatch(
    pairs: Sequence[tuple[Capability, CapabilityHandler]],
) -> dict[Capability, CapabilityHandler]:
    result: dict[Capability, CapabilityHandler] = {}
    for capability, handler in pairs:
        if capability in result:
            raise ValueError(f"duplicate capability registration: {capability.value}")
        result[capability] = handler
    return result


HANDLERS = build_dispatch(HANDLER_PAIRS)


def dispatch(
    capability: Capability,
    context: CommandContext,
    runner: ProcessRunner = run_process,
) -> int:
    handler = HANDLERS.get(capability)
    if handler is None:
        print(f"capability={capability.value} is not available through Stage-1")
        return 2
    return handler(context, runner)
