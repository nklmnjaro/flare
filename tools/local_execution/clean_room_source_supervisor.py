import ctypes
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from types import FrameType
from typing import Literal

PR_SET_CHILD_SUBREAPER = 36
MAX_COMMAND_EXIT = 248
OUTPUT_LIMIT_EXIT = 249
DESCENDANT_EXIT = 250
TIMEOUT_EXIT = 251
SHUTDOWN_EXIT = 253
CLEANUP_UNCERTAIN_EXIT = 254
SHUTDOWN_SECONDS = 5
MAX_PROCESS_OUTPUT_BYTES = 1_000_000
MAX_SUPERVISED_PROCESSES = 1_024
MAX_TASKS_PER_PROCESS = 256
MAX_PROC_FILE_BYTES = 65_536

type StopState = Literal["absent", "running", "stopped"]
type DiscoveryHook = Callable[[int], None]


class SupervisorError(RuntimeError):
    pass


def _become_subreaper() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise SupervisorError(f"prctl subreaper failed: errno={error}")


def _require_before(deadline: float, operation: str) -> None:
    if time.monotonic() >= deadline:
        raise SupervisorError(f"{operation} exceeded the supervision time bound")


def _task_identifiers(task_root: Path, deadline: float) -> tuple[int, ...]:
    values: list[int] = []
    with os.scandir(task_root) as entries:
        for entry in entries:
            _require_before(deadline, "process task scan")
            if not entry.name.isascii() or not entry.name.isdigit():
                continue
            if len(values) >= MAX_TASKS_PER_PROCESS:
                raise SupervisorError(
                    "process task count exceeds the supervision bound"
                )
            values.append(int(entry.name))
    _require_before(deadline, "process task scan")
    return tuple(sorted(values))


def _proc_text(path: Path, deadline: float) -> str:
    _require_before(deadline, "process metadata read")
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        chunks: list[bytes] = []
        remaining = MAX_PROC_FILE_BYTES + 1
        while remaining:
            _require_before(deadline, "process metadata read")
            chunk = os.read(descriptor, min(4_096, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        os.close(descriptor)
    _require_before(deadline, "process metadata read")
    raw = b"".join(chunks)
    if len(raw) > MAX_PROC_FILE_BYTES:
        raise SupervisorError("process metadata exceeds the byte bound")
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise SupervisorError("process metadata is not ASCII") from error


def _direct_children(
    identifier: int,
    *,
    deadline: float | None = None,
    captured: set[int] | None = None,
    on_discovery: DiscoveryHook | None = None,
) -> tuple[int, ...]:
    task_root = Path(f"/proc/{identifier}/task")
    limit = time.monotonic() + SHUTDOWN_SECONDS if deadline is None else deadline
    while True:
        if time.monotonic() >= limit:
            raise SupervisorError("descendant task state did not stabilize")
        children_path: Path | None = None
        try:
            tasks = _task_identifiers(task_root, limit)
            values: set[int] = set()
            for task in tasks:
                children_path = task_root / str(task) / "children"
                raw = _proc_text(children_path, limit)
                for match in re.finditer(r"\S+", raw):
                    value = match.group()
                    if not value.isascii() or not value.isdigit():
                        raise SupervisorError("invalid descendant process identifier")
                    child = int(value)
                    if child < 2:
                        raise SupervisorError("invalid descendant process identifier")
                    if child in values:
                        continue
                    if len(values) >= MAX_SUPERVISED_PROCESSES:
                        raise SupervisorError(
                            "child count exceeds the supervision bound"
                        )
                    values.add(child)
                    if captured is not None:
                        if (
                            child not in captured
                            and len(captured) >= MAX_SUPERVISED_PROCESSES
                        ):
                            raise SupervisorError(
                                "descendant count exceeds the supervision bound"
                            )
                        captured.add(child)
                    if on_discovery is not None:
                        on_discovery(child)
            observed_tasks = _task_identifiers(task_root, limit)
        except FileNotFoundError as error:
            if not task_root.exists():
                if identifier == os.getpid():
                    raise SupervisorError(
                        "self process task state is unavailable"
                    ) from error
                return ()
            if (
                identifier == os.getpid()
                and children_path is not None
                and children_path.exists()
            ):
                raise SupervisorError(
                    "self process descendant state is unavailable"
                ) from error
            continue
        except OSError as error:
            raise SupervisorError(
                f"descendant process state is unreadable: errno={error.errno}"
            ) from error
        else:
            if tasks == observed_tasks:
                _require_before(limit, "descendant task scan")
                return tuple(sorted(values))


def descendant_processes(
    root: int,
    *,
    deadline: float | None = None,
    captured: set[int] | None = None,
    on_discovery: DiscoveryHook | None = None,
) -> tuple[int, ...]:
    limit = time.monotonic() + SHUTDOWN_SECONDS if deadline is None else deadline
    registry = set() if captured is None else captured
    first = _direct_children(
        root,
        deadline=limit,
        captured=registry,
        on_discovery=on_discovery,
    )
    pending = [(identifier, 1) for identifier in first]
    queued = set(first)
    observed: dict[int, int] = {}
    while pending:
        _require_before(limit, "descendant traversal")
        identifier, depth = pending.pop()
        queued.discard(identifier)
        if identifier in observed:
            continue
        if len(observed) >= MAX_SUPERVISED_PROCESSES:
            raise SupervisorError("descendant count exceeds the supervision bound")
        observed[identifier] = depth
        children = _direct_children(
            identifier,
            deadline=limit,
            captured=registry,
            on_discovery=on_discovery,
        )
        for child in children:
            if child in observed or child in queued:
                continue
            if len(observed) + len(queued) >= MAX_SUPERVISED_PROCESSES:
                raise SupervisorError("descendant count exceeds the supervision bound")
            queued.add(child)
            pending.append((child, depth + 1))
    _require_before(limit, "descendant traversal")
    return tuple(
        identifier
        for identifier, _ in sorted(
            observed.items(),
            key=lambda item: (-item[1], -item[0]),
        )
    )


def process_stop_state(
    identifier: int,
    deadline: float | None = None,
) -> StopState:
    limit = time.monotonic() + SHUTDOWN_SECONDS if deadline is None else deadline
    task_root = Path(f"/proc/{identifier}/task")
    while True:
        _require_before(limit, "process state scan")
        try:
            tasks = _task_identifiers(task_root, limit)
            states: list[str] = []
            for task in tasks:
                raw = _proc_text(task_root / str(task) / "status", limit)
                state = next(
                    (
                        line.split()[1]
                        for line in raw.splitlines()
                        if line.startswith("State:")
                    ),
                    None,
                )
                if state is None:
                    raise SupervisorError("process task state is incomplete")
                states.append(state)
            observed_tasks = _task_identifiers(task_root, limit)
        except FileNotFoundError:
            if not task_root.exists():
                return "absent"
            continue
        if tasks != observed_tasks:
            continue
        _require_before(limit, "process state scan")
        if not states or all(state in {"X", "Z"} for state in states):
            return "absent"
        if all(state in {"T", "t"} for state in states):
            return "stopped"
        return "running"


def _descendants() -> tuple[int, ...]:
    return descendant_processes(os.getpid())


def _reap(deadline: float | None = None) -> None:
    limit = time.monotonic() + SHUTDOWN_SECONDS if deadline is None else deadline
    reaped = 0
    while True:
        _require_before(limit, "descendant reap")
        try:
            identifier, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if identifier == 0:
            return
        reaped += 1
        if reaped > MAX_SUPERVISED_PROCESSES:
            raise SupervisorError("reaped process count exceeds the supervision bound")


def _terminate_descendants() -> None:
    deadline = time.monotonic() + SHUTDOWN_SECONDS
    captured: set[int] = set()

    def stop(identifier: int) -> None:
        try:
            os.kill(identifier, signal.SIGSTOP)
        except ProcessLookupError:
            return

    try:
        empty_observations = 0
        while True:
            descendants = descendant_processes(
                os.getpid(),
                deadline=deadline,
                captured=captured,
                on_discovery=stop,
            )
            for identifier in captured:
                try:
                    os.kill(identifier, signal.SIGKILL)
                except ProcessLookupError:
                    continue
            _reap(deadline)
            active = {
                identifier
                for identifier in captured | set(descendants)
                if process_stop_state(identifier, deadline) != "absent"
            }
            captured.intersection_update(active)
            empty_observations = empty_observations + 1 if not active else 0
            if empty_observations >= 2:
                return
            _require_before(deadline, "descendant cleanup")
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
    except BaseException:
        pending = sys.exception()
        for identifier in captured:
            with suppress(BaseException):
                os.kill(identifier, signal.SIGSTOP)
        for identifier in captured:
            with suppress(BaseException):
                os.kill(identifier, signal.SIGKILL)
        if pending is not None:
            raise pending
        raise


def _normalized_exit(returncode: int) -> int:
    if returncode < 0:
        return min(MAX_COMMAND_EXIT, 128 - returncode)
    return min(MAX_COMMAND_EXIT, returncode)


def _capture_ready_output(
    selector: selectors.BaseSelector,
    buffers: dict[str, bytearray],
) -> bool:
    for key, _ in selector.select(timeout=0.05):
        stream = key.fileobj
        if not hasattr(stream, "fileno"):
            raise SupervisorError("process output stream has no descriptor")
        remaining = MAX_PROCESS_OUTPUT_BYTES - sum(map(len, buffers.values()))
        try:
            raw = os.read(stream.fileno(), min(65_536, remaining + 1))
        except BlockingIOError:
            continue
        if not raw:
            selector.unregister(stream)
            continue
        if len(raw) > remaining:
            return True
        buffers[str(key.data)].extend(raw)
    return False


def _capture_process(
    process: subprocess.Popen[bytes],
    timeout: int,
    shutdown_requested: Callable[[], bool],
) -> tuple[int, dict[str, bytearray]]:
    if process.stdout is None or process.stderr is None:
        _terminate_descendants()
        raise SupervisorError("process output pipes are unavailable")
    buffers = {"stderr": bytearray(), "stdout": bytearray()}
    deadline = time.monotonic() + timeout
    with process.stdout, process.stderr, selectors.DefaultSelector() as selector:
        for label, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, label)
        while True:
            if shutdown_requested():
                _terminate_descendants()
                return SHUTDOWN_EXIT, buffers
            if time.monotonic() >= deadline:
                _terminate_descendants()
                return TIMEOUT_EXIT, buffers
            if _capture_ready_output(selector, buffers):
                _terminate_descendants()
                return OUTPUT_LIMIT_EXIT, buffers
            returncode = process.poll()
            if returncode is None:
                continue
            _reap(time.monotonic() + SHUTDOWN_SECONDS)
            if _descendants():
                _terminate_descendants()
                return DESCENDANT_EXIT, buffers
            if not selector.get_map():
                return _normalized_exit(returncode), buffers


def _publish_output(buffers: dict[str, bytearray]) -> None:
    sys.stdout.buffer.write(buffers["stdout"])
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(buffers["stderr"])
    sys.stderr.buffer.flush()


def supervise(argv: tuple[str, ...], timeout: int) -> int:
    if not argv or timeout < 1:
        raise SupervisorError("invalid supervisor command")
    _become_subreaper()
    shutdown_requested = False

    def request_shutdown(_signal: int, _frame: FrameType | None) -> None:
        nonlocal shutdown_requested
        shutdown_requested = True

    previous_handler = signal.signal(signal.SIGTERM, request_shutdown)
    try:
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            exit_code, buffers = _capture_process(
                process,
                timeout,
                lambda: shutdown_requested,
            )
        except BaseException:
            _terminate_descendants()
            process.poll()
            raise
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
    _publish_output(buffers)
    if exit_code == TIMEOUT_EXIT:
        print("clean-room supervisor: command timed out", file=sys.stderr)
    elif exit_code == DESCENDANT_EXIT:
        print("clean-room supervisor: descendant process rejected", file=sys.stderr)
    elif exit_code == SHUTDOWN_EXIT:
        print("clean-room supervisor: outer shutdown requested", file=sys.stderr)
    return exit_code


def main(arguments: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if arguments is None else arguments)
    if len(values) < 3 or values[1] != "--":
        print("usage: clean_room_supervisor.py TIMEOUT -- COMMAND...", file=sys.stderr)
        return 252
    try:
        timeout = int(values[0])
        return supervise(tuple(values[2:]), timeout)
    except (OSError, SupervisorError, ValueError) as error:
        print(f"clean-room supervisor: ERROR {error}", file=sys.stderr)
        # Keep the subreaper alive with its descendants attached. The parent
        # treats this exit as an explicit fallback request and proves cleanup
        # through /proc before returning RED.
        os.kill(os.getpid(), signal.SIGSTOP)
        return CLEANUP_UNCERTAIN_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
