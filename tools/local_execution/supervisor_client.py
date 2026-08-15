import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from functools import partial

from tools.local_execution.clean_room_source_supervisor import (
    SHUTDOWN_SECONDS,
    StopState,
    SupervisorError,
    descendant_processes,
    process_stop_state,
)

type Finalizer = Callable[[], int | None]


class SupervisorClientError(RuntimeError):
    pass


def _stop_state(identifier: int, deadline: float | None = None) -> StopState:
    try:
        return process_stop_state(identifier, deadline)
    except SupervisorError as error:
        raise SupervisorClientError(str(error)) from error


def _stopped(identifier: int, deadline: float | None = None) -> bool:
    return _stop_state(identifier, deadline) == "stopped"


def communicate_supervisor(
    process: subprocess.Popen[bytes], timeout: float
) -> tuple[bytes, bytes]:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            return process.communicate(timeout=min(0.1, remaining))
        except subprocess.TimeoutExpired:
            if _stopped(process.pid, deadline):
                _force_cleanup(process)
                return process.communicate()


def _signal(identifier: int, requested: signal.Signals) -> None:
    try:
        os.kill(identifier, requested)
    except ProcessLookupError:
        return


def _pause(deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return
    time.sleep(min(0.01, remaining))


def _stop_discovered(identifier: int) -> None:
    _signal(identifier, signal.SIGSTOP)


def _stable_descendants(
    root: int,
    captured: set[int],
    deadline: float,
) -> bool:
    previous: frozenset[int] | None = None
    while time.monotonic() < deadline:
        descendants = set(
            descendant_processes(
                root,
                deadline=deadline,
                captured=captured,
                on_discovery=_stop_discovered,
            )
        )
        states = {
            identifier: _stop_state(identifier, deadline)
            for identifier in tuple(captured)
        }
        absent = {
            identifier for identifier, state in states.items() if state == "absent"
        }
        captured.difference_update(absent)
        descendants.difference_update(absent)
        for identifier, state in states.items():
            if state == "running":
                _signal(identifier, signal.SIGSTOP)
        current = frozenset(descendants)
        if (
            current == frozenset(captured)
            and current == previous
            and all(state != "running" for state in states.values())
        ):
            return True
        previous = current if current == frozenset(captured) else None
        _pause(deadline)
    return False


def _kill_stopped_descendants(
    root: int,
    captured: set[int],
    deadline: float,
) -> bool:
    empty_observations = 0
    while time.monotonic() < deadline:
        descendant_processes(
            root,
            deadline=deadline,
            captured=captured,
            on_discovery=_stop_discovered,
        )
        active: set[int] = set()
        for identifier in tuple(captured):
            state = _stop_state(identifier, deadline)
            if state == "absent":
                captured.discard(identifier)
            else:
                active.add(identifier)
        for identifier in active:
            _signal(identifier, signal.SIGSTOP)
        for identifier in active:
            _signal(identifier, signal.SIGKILL)
        empty_observations = empty_observations + 1 if not active else 0
        if empty_observations >= 2:
            return True
        _pause(deadline)
    return False


def _record_finalizer(
    errors: list[str],
    interruptions: list[BaseException],
    label: str,
    operation: Finalizer,
) -> None:
    completed = False
    with suppress(BaseException):
        try:
            operation()
            completed = True
        finally:
            if not completed:
                error = sys.exception()
                errors.append(f"{label}: {type(error).__name__}: {error}")
                if error is not None and not isinstance(error, Exception):
                    interruptions.append(error)


def _attempt_phase(
    errors: list[str],
    label: str,
    operation: Finalizer,
) -> BaseException | None:
    interruptions: list[BaseException] = []
    _record_finalizer(errors, interruptions, label, operation)
    return interruptions[0] if interruptions else None


def _best_effort_teardown(
    process: subprocess.Popen[bytes],
    captured: set[int],
    deadline: float,
) -> tuple[list[str], BaseException | None]:
    errors: list[str] = []
    interruptions: list[BaseException] = []
    operations: list[tuple[str, Finalizer]] = []
    for identifier in tuple(captured):
        operations.append(
            (
                f"stop descendant {identifier}",
                partial(_signal, identifier, signal.SIGSTOP),
            )
        )
    for identifier in tuple(captured):
        operations.append(
            (
                f"kill descendant {identifier}",
                partial(_signal, identifier, signal.SIGKILL),
            )
        )
    operations.extend(
        (
            (
                "kill supervisor process group",
                lambda: os.killpg(process.pid, signal.SIGKILL),
            ),
            (
                "continue supervisor",
                lambda: _signal(process.pid, signal.SIGCONT),
            ),
            ("kill supervisor", lambda: _signal(process.pid, signal.SIGKILL)),
        )
    )
    alive = [True]

    def observe_supervisor() -> None:
        alive[0] = process.poll() is None

    operations.extend(
        (
            (
                "reap supervisor",
                lambda: process.wait(timeout=max(0.05, deadline - time.monotonic())),
            ),
            ("observe supervisor", observe_supervisor),
        )
    )
    for label, operation in operations:
        _record_finalizer(
            errors,
            interruptions,
            label,
            operation,
        )
    if alive[0]:
        errors.append("supervisor remained alive after SIGKILL")
    return errors, (interruptions[0] if interruptions else None)


def _clean_stopped_tree(
    process: subprocess.Popen[bytes],
    captured: set[int],
    deadline: float,
) -> None:
    _signal(process.pid, signal.SIGSTOP)
    state = _stop_state(process.pid, deadline)
    while state == "running":
        if time.monotonic() >= deadline:
            raise SupervisorClientError("supervisor did not stop")
        _pause(deadline)
        state = _stop_state(process.pid, deadline)
    if state == "absent":
        raise SupervisorClientError("supervisor disappeared before descendant capture")
    if not _stable_descendants(process.pid, captured, deadline):
        raise SupervisorClientError("descendant set did not stabilize")
    if not _kill_stopped_descendants(process.pid, captured, deadline):
        raise SupervisorClientError("descendant absence did not stabilize")


def _final_descendant_scan(
    process: subprocess.Popen[bytes],
    captured: set[int],
    deadline: float,
) -> None:
    descendant_processes(
        process.pid,
        deadline=deadline,
        captured=captured,
        on_discovery=_stop_discovered,
    )


def _force_cleanup(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        process.wait()
        return
    deadline = time.monotonic() + SHUTDOWN_SECONDS
    captured: set[int] = set()
    problems: list[str] = []
    interruption: BaseException | None = None
    try:
        interruption = _attempt_phase(
            problems,
            "descendant cleanup failed",
            partial(_clean_stopped_tree, process, captured, deadline),
        )
    finally:
        try:
            scan_interruption = _attempt_phase(
                problems,
                "final descendant scan failed",
                partial(_final_descendant_scan, process, captured, deadline),
            )
            interruption = interruption or scan_interruption
        finally:
            teardown_errors, teardown_interruption = _best_effort_teardown(
                process,
                captured,
                deadline,
            )
            problems.extend(teardown_errors)
            interruption = interruption or teardown_interruption
    if interruption is not None:
        raise interruption
    if problems:
        raise SupervisorClientError(
            "supervisor cleanup uncertain: " + "; ".join(problems)
        )


def shutdown_supervisor(process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
    if process.poll() is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    try:
        return communicate_supervisor(process, SHUTDOWN_SECONDS + 5)
    except subprocess.TimeoutExpired:
        _force_cleanup(process)
        return process.communicate()
    except BaseException:
        _force_cleanup(process)
        raise
