import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tools.local_execution.clean_room_source_supervisor import (
    DESCENDANT_EXIT,
    MAX_PROCESS_OUTPUT_BYTES,
    OUTPUT_LIMIT_EXIT,
    SHUTDOWN_EXIT,
    TIMEOUT_EXIT,
)
from tools.local_execution.model import ProcessResult
from tools.local_execution.profile import HostProfile
from tools.local_execution.supervisor_client import (
    communicate_supervisor,
    shutdown_supervisor,
)

MAX_DIAGNOSTIC_BYTES = 12_000
DEFAULT_TIMEOUT_SECONDS = 900
SUPERVISOR_GRACE_SECONDS = 15
SUPERVISOR = Path(__file__).with_name("clean_room_source_supervisor.py")
_OUTPUT_LIMIT_RETURN_CODE = 125
_DESCENDANT_RETURN_CODE = 126
_INVOCATION_RETURN_CODE = 127
_TIMEOUT_RETURN_CODE = 124


@dataclass(frozen=True, slots=True)
class ProcessSpec:
    label: str
    argv: tuple[str, ...]
    environment: tuple[tuple[str, str], ...] = ()
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.timeout_seconds < 1:
            raise ValueError("process timeout must be a positive number of seconds")


@dataclass(frozen=True, slots=True)
class CommandContext:
    root: Path
    profile: HostProfile
    uv: Path


type ProcessRunner = Callable[[ProcessSpec, Path], ProcessResult]


def _bound(encoded: bytes) -> str:
    if len(encoded) <= MAX_DIAGNOSTIC_BYTES:
        return encoded.decode("utf-8", "replace")
    half = (MAX_DIAGNOSTIC_BYTES - 80) // 2
    omitted = len(encoded) - (half * 2)
    return (
        encoded[:half].decode("utf-8", "replace")
        + f"\n... [TRUNCATED {omitted} BYTES] ...\n"
        + encoded[-half:].decode("utf-8", "replace")
    )


def _diagnostic(stderr: bytes, message: str) -> bytes:
    separator = b"" if not stderr or stderr.endswith(b"\n") else b"\n"
    return stderr + separator + message.encode("utf-8") + b"\n"


def _normalized_execution(
    returncode: int,
    stdout: bytes,
    stderr: bytes,
    timeout: int,
) -> tuple[int, bytes, bytes]:
    if returncode == OUTPUT_LIMIT_EXIT:
        message = (
            f"command exceeded its combined {MAX_PROCESS_OUTPUT_BYTES}-byte "
            "output bound"
        )
        return _OUTPUT_LIMIT_RETURN_CODE, stdout, _diagnostic(stderr, message)
    if returncode == DESCENDANT_EXIT:
        message = "command left a descendant process tree"
        return _DESCENDANT_RETURN_CODE, stdout, _diagnostic(stderr, message)
    if returncode in {TIMEOUT_EXIT, SHUTDOWN_EXIT}:
        message = f"command exceeded its explicit {timeout}-second local bound"
        return _TIMEOUT_RETURN_CODE, stdout, _diagnostic(stderr, message)
    if returncode >= OUTPUT_LIMIT_EXIT:
        message = "command invocation failed inside the process supervisor"
        return _INVOCATION_RETURN_CODE, stdout, _diagnostic(stderr, message)
    return returncode, stdout, stderr


def _result(
    specification: ProcessSpec,
    returncode: int,
    stdout: bytes,
    stderr: bytes,
    started: float,
) -> ProcessResult:
    return ProcessResult(
        specification.label,
        returncode,
        _bound(stdout),
        _bound(stderr),
        time.monotonic() - started,
    )


def run_process(specification: ProcessSpec, root: Path) -> ProcessResult:
    environment = os.environ.copy()
    for name in (
        "FLARE_ALLURE_RESULTS",
        "FLARE_LOCAL_ALLURE_RESULTS",
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
    ):
        environment.pop(name, None)
    environment["PATH"] = "/usr/bin:/bin"
    environment.update(dict(specification.environment))
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    started = time.monotonic()
    supervised = (
        sys.executable,
        "-I",
        "-B",
        str(SUPERVISOR),
        str(specification.timeout_seconds),
        "--",
        *specification.argv,
    )
    try:
        process = subprocess.Popen(
            supervised,
            cwd=root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as error:
        message = f"command invocation failed: {type(error).__name__}"
        return _result(
            specification,
            _INVOCATION_RETURN_CODE,
            b"",
            message.encode("utf-8"),
            started,
        )
    try:
        stdout, stderr = communicate_supervisor(
            process,
            specification.timeout_seconds + SUPERVISOR_GRACE_SECONDS,
        )
    except BaseException as error:
        try:
            stdout, stderr = shutdown_supervisor(process)
        except BaseException as cleanup_error:
            message = f"supervisor cleanup failed: {cleanup_error}"
            if isinstance(error, subprocess.TimeoutExpired):
                return _result(
                    specification,
                    _INVOCATION_RETURN_CODE,
                    b"",
                    message.encode("utf-8"),
                    started,
                )
            raise RuntimeError(message) from cleanup_error
        if isinstance(error, subprocess.TimeoutExpired):
            message = "process supervisor exceeded its outer cleanup bound"
            return _result(
                specification,
                _TIMEOUT_RETURN_CODE,
                stdout,
                _diagnostic(stderr, message),
                started,
            )
        raise
    returncode, stdout, stderr = _normalized_execution(
        process.returncode,
        stdout,
        stderr,
        specification.timeout_seconds,
    )
    return _result(specification, returncode, stdout, stderr, started)


def _render_result(result: ProcessResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    print(
        f"leaf={result.label} status={status} "
        f"exit={result.returncode} duration={result.duration_seconds:.3f}s"
    )
    if not result.passed:
        if result.stdout.strip():
            print(f"stdout[{result.label}]:\n{result.stdout.rstrip()}")
        if result.stderr.strip():
            print(f"stderr[{result.label}]:\n{result.stderr.rstrip()}")


def run_specs(
    context: CommandContext,
    runner: ProcessRunner,
    specifications: Sequence[ProcessSpec],
    *,
    fail_fast: bool,
) -> int:
    failed = False
    for specification in specifications:
        result = runner(specification, context.root)
        _render_result(result)
        failed = failed or not result.passed
        if failed and fail_fast:
            break
    return 1 if failed else 0
