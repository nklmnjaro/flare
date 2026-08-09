import os
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tools.local_execution.model import ProcessResult
from tools.local_execution.profile import HostProfile

MAX_DIAGNOSTIC_BYTES = 12_000


@dataclass(frozen=True, slots=True)
class ProcessSpec:
    label: str
    argv: tuple[str, ...]
    environment: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class CommandContext:
    root: Path
    profile: HostProfile
    uv: Path


type ProcessRunner = Callable[[ProcessSpec, Path], ProcessResult]


def _bound(value: str) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= MAX_DIAGNOSTIC_BYTES:
        return value
    half = (MAX_DIAGNOSTIC_BYTES - 80) // 2
    omitted = len(encoded) - (half * 2)
    return (
        encoded[:half].decode("utf-8", "replace")
        + f"\n... [TRUNCATED {omitted} BYTES] ...\n"
        + encoded[-half:].decode("utf-8", "replace")
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
    started = time.monotonic()
    try:
        completed = subprocess.run(
            specification.argv,
            cwd=root,
            env=environment,
            capture_output=True,
            check=False,
            text=True,
            timeout=900,
        )
        return ProcessResult(
            specification.label,
            completed.returncode,
            _bound(completed.stdout),
            _bound(completed.stderr),
            time.monotonic() - started,
        )
    except subprocess.TimeoutExpired:
        return ProcessResult(
            specification.label,
            124,
            "",
            "command exceeded its explicit 900-second local bound",
            time.monotonic() - started,
        )
    except OSError as error:
        return ProcessResult(
            specification.label,
            127,
            "",
            f"command invocation failed: {type(error).__name__}",
            time.monotonic() - started,
        )


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
