import subprocess
import time
from dataclasses import dataclass
from re import compile as compile_pattern
from re import escape as escape_pattern
from shlex import join as shell_join

from tools.project_state.model import JSONValue, ValidationResult
from tools.quality.tests.project_state.reporting import (
    attach_json,
    attach_text,
    step_context,
)

MAX_STREAM_BYTES = 4_096
REDACTION_MARKER = "REDACTED_SUPPORTED_SECRET"
SYNTHETIC_SECRET_CANARY = "flare-closure-secret-canary"
_HEAD_BYTES = MAX_STREAM_BYTES // 2
_SECRET_NAMES = ("authorization", "password", "secret", "token")
_SECRET_NAME_PATTERN = "|".join(_SECRET_NAMES)
_REDACTION_MARKER_PATTERN = escape_pattern(REDACTION_MARKER)
_QUOTED_OR_BARE_SECRET_NAME = (
    rf'(?:{_SECRET_NAME_PATTERN}|"(?:{_SECRET_NAME_PATTERN})"'
    rf"|'(?:{_SECRET_NAME_PATTERN})')"
)
_SECRET_ASSIGNMENT = compile_pattern(
    rf"(?i)(?<![a-z0-9_])(?:"
    rf"--(?:{_SECRET_NAME_PATTERN})(?:\s*+=\s*+|\s++)"
    rf"|{_QUOTED_OR_BARE_SECRET_NAME}\s*+(?:=|:)\s*+)"
    rf"(?!{_REDACTION_MARKER_PATTERN}(?:$|\s|[\"']))"
)
_SECRET_OPTION = compile_pattern(rf"(?i)^--(?:{_SECRET_NAME_PATTERN})$")
_SECRET_OPTION_ASSIGNMENT = compile_pattern(
    rf"(?i)^(?P<prefix>--(?:{_SECRET_NAME_PATTERN})\s*=\s*)[\s\S]*$"
)
_SECRET_KEY_ASSIGNMENT = compile_pattern(
    rf"(?i)^(?P<prefix>{_QUOTED_OR_BARE_SECRET_NAME}\s*(?:=|:)\s*)[\s\S]*$"
)


@dataclass(frozen=True, slots=True)
class CommandResult:
    rendered_command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int

    def output_json(self) -> dict[str, JSONValue]:
        result: dict[str, JSONValue] = {
            "duration_ms": self.duration_ms,
            "exit_code": self.exit_code,
        }
        if self.stdout:
            result["stdout"] = self.stdout
        if self.stderr:
            result["stderr"] = self.stderr
        return result


class CommandExitError(RuntimeError):
    def __init__(self, result: CommandResult) -> None:
        self.exit_code = result.exit_code
        self.rendered_command = result.rendered_command
        self.diagnostic = (
            f"command exited {result.exit_code}: {result.rendered_command}"
        )
        super().__init__(self.diagnostic)


@dataclass(frozen=True, slots=True)
class ValidationObservation:
    result: ValidationResult
    check_argv: tuple[str, ...]


def render_command(argv: tuple[str, ...]) -> str:
    safe_argv = _safe_argv(argv)
    return _redact_text(shell_join(safe_argv))


def run_command(
    argv: tuple[str, ...],
    *,
    expected_exit_codes: frozenset[int] = frozenset({0}),
    step_title: str | None = None,
    attach_success: bool = False,
) -> CommandResult:
    rendered_command = render_command(argv)
    started = time.monotonic_ns()
    process = subprocess.run(argv, capture_output=True, check=False)
    result = CommandResult(
        rendered_command=rendered_command,
        exit_code=process.returncode,
        stdout=_bounded(process.stdout),
        stderr=_bounded(process.stderr),
        duration_ms=(time.monotonic_ns() - started) // 1_000_000,
    )

    unexpected = result.exit_code not in expected_exit_codes
    expected_failure = result.exit_code != 0 and not unexpected
    evidence_title = step_title
    if evidence_title is None and unexpected:
        evidence_title = "Record unexpected console command failure"
    if evidence_title is not None:
        with step_context(evidence_title):
            attach_text("command", result.rendered_command)
            if attach_success or unexpected or expected_failure:
                attach_json("command output", result.output_json())
            if unexpected:
                raise CommandExitError(result)

    if unexpected:
        raise CommandExitError(result)
    return result


def _redact_text(value: str) -> str:
    return "\n".join(
        REDACTION_MARKER if _contains_secret_assignment(line) else line
        for line in value.splitlines()
    )


def _bounded(value: bytes) -> str:
    safe = _redact_text(value.decode("utf-8", "replace"))
    encoded = safe.encode("utf-8")
    if len(encoded) <= MAX_STREAM_BYTES:
        return safe
    omitted = len(encoded) - MAX_STREAM_BYTES
    head = encoded[:_HEAD_BYTES].decode("utf-8", "replace")
    tail = encoded[-_HEAD_BYTES:].decode("utf-8", "replace")
    marker = f"\n...[TRUNCATED {omitted} BYTES]...\n"
    return f"{head}{marker}{tail}"


def _safe_argv(argv: tuple[str, ...]) -> tuple[str, ...]:
    safe: list[str] = []
    redact_next = False
    for argument in argv:
        if redact_next:
            safe.append(REDACTION_MARKER)
            redact_next = False
        elif _SECRET_OPTION.fullmatch(argument) is not None:
            safe.append(argument)
            redact_next = True
        else:
            safe.append(_safe_argument(argument))
    return tuple(safe)


def _safe_argument(argument: str) -> str:
    for pattern in (_SECRET_OPTION_ASSIGNMENT, _SECRET_KEY_ASSIGNMENT):
        matched = pattern.fullmatch(argument)
        if matched is not None:
            return f"{matched.group('prefix')}{REDACTION_MARKER}"
    return REDACTION_MARKER if _contains_secret_assignment(argument) else argument


def _contains_secret_assignment(value: str) -> bool:
    inspection = value.replace(r"\r", "\n").replace(r"\n", "\n")
    return _SECRET_ASSIGNMENT.search(inspection) is not None
