import json
import sys

from tools.quality.tests.project_state.assertions import (
    assert_cli_exit_mismatch_rejected,
    assert_command_evidence_policy,
    assert_command_failure_evidence,
    assert_command_grammar,
)
from tools.quality.tests.project_state.command_evidence import (
    SYNTHETIC_SECRET_CANARY,
    ValidationObservation,
    render_command,
    run_command,
)
from tools.quality.tests.project_state.support import RepositoryFixture

_SUPPORTED_SECRET_NAMES = ("authorization", "password", "secret", "token")


def _fake_cli_observation(
    observation: ValidationObservation,
    exit_code: int,
) -> ValidationObservation:
    rendered = json.dumps(observation.result.as_dict(), sort_keys=True)
    script = f"print({rendered!r}); raise SystemExit({exit_code})"
    return ValidationObservation(observation.result, (sys.executable, "-c", script))


def verify_a1_c08_cli_exit_contract(repository: RepositoryFixture) -> None:
    defect = repository.validate(raw=b'{"schema_version":\n')
    assert_cli_exit_mismatch_rejected(_fake_cli_observation(defect, 0))
    passing = repository.validate()
    assert_cli_exit_mismatch_rejected(_fake_cli_observation(passing, 1))


def verify_a1_c09_command_evidence_policy(repository: RepositoryFixture) -> None:
    del repository
    assert_command_grammar(_render_grammar_cases(), SYNTHETIC_SECRET_CANARY)
    script = (
        "import sys; "
        "sys.stdout.write("
        f"'x' * 7000 + '\\ntoken={SYNTHETIC_SECRET_CANARY}\\n'); "
        "sys.stderr.write("
        "'diagnostic-before\\n"
        f"TOKEN={SYNTHETIC_SECRET_CANARY}\\n"
        "diagnostic-after\\n')"
    )
    result = run_command(
        (
            sys.executable,
            "-c",
            script,
            "visible-before",
            "--label=clear",
            "visible-after",
        ),
        step_title="Produce oversized output containing a synthetic secret canary",
        attach_success=True,
    )
    assert_command_evidence_policy(
        result,
        SYNTHETIC_SECRET_CANARY,
        expected_command_fragments=(
            sys.executable,
            "-c",
            "visible-before",
            "--label=clear",
            "visible-after",
        ),
        expected_stderr_fragments=("diagnostic-before", "diagnostic-after"),
    )
    failure_script = (
        "import sys; "
        "sys.stderr.write('expected failure detail\\n'); "
        "raise SystemExit(7)"
    )
    assert_command_failure_evidence(
        (
            sys.executable,
            "-c",
            failure_script,
            "--token",
            SYNTHETIC_SECRET_CANARY,
            "failure-visible",
        ),
        SYNTHETIC_SECRET_CANARY,
    )


def _render_grammar_cases() -> tuple[tuple[str, str, str | None], ...]:
    cases: list[tuple[str, tuple[str, ...], str | None]] = []
    for name in _SUPPORTED_SECRET_NAMES:
        cases.extend(
            (
                (
                    f"{name} key assignment",
                    (f"{name}={SYNTHETIC_SECRET_CANARY}",),
                    f"{name}=",
                ),
                (
                    f"{name} inline option",
                    (f"--{name}={SYNTHETIC_SECRET_CANARY}",),
                    f"--{name}=",
                ),
                (
                    f"{name} split option",
                    (f"--{name}", SYNTHETIC_SECRET_CANARY),
                    f"--{name}",
                ),
            )
        )
    cases.extend(
        (
            (
                "colon assignment",
                (f"token: {SYNTHETIC_SECRET_CANARY}",),
                "token:",
            ),
            (
                "double-quoted exact key",
                (f'"token": {SYNTHETIC_SECRET_CANARY}',),
                '"token":',
            ),
            (
                "single-quoted exact key",
                (f"'token': {SYNTHETIC_SECRET_CANARY}",),
                "token",
            ),
            (
                "case-insensitive key",
                (f"TOKEN={SYNTHETIC_SECRET_CANARY}",),
                "TOKEN=",
            ),
            (
                "actual LF boundary",
                (f"prefix\ntoken={SYNTHETIC_SECRET_CANARY}",),
                None,
            ),
            (
                "actual CR boundary",
                (f"prefix\rtoken={SYNTHETIC_SECRET_CANARY}",),
                None,
            ),
            (
                "literal escaped LF boundary",
                (rf"prefix\ntoken={SYNTHETIC_SECRET_CANARY}",),
                None,
            ),
            (
                "literal escaped CR boundary",
                (rf"prefix\rtoken={SYNTHETIC_SECRET_CANARY}",),
                None,
            ),
            (
                "embedded source assignment",
                (f"print('before'); token={SYNTHETIC_SECRET_CANARY}; print('after')",),
                None,
            ),
        )
    )
    return tuple(
        (
            label,
            render_command(("flare-evidence-command", *arguments)),
            preserved,
        )
        for label, arguments, preserved in cases
    )
