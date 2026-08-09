from collections.abc import Collection

from tools.project_state.json_codec import parse_strict_json
from tools.project_state.model import (
    Finding,
    JSONValue,
    PublicationResult,
    PublicationStatus,
    ValidationResult,
    ValidationStatus,
)
from tools.quality.tests.project_state.command_evidence import (
    REDACTION_MARKER,
    CommandExitError,
    CommandResult,
    ValidationObservation,
    run_command,
)
from tools.quality.tests.project_state.reporting import attach_json, step_context

type FindingSource = Collection[Finding] | ValidationObservation


def _finding_labels(findings: Collection[Finding]) -> list[str]:
    return sorted(f"{finding.code.value}:{finding.context}" for finding in findings)


def _reproduce_validation(observation: ValidationObservation) -> None:
    expected_exit = 0 if observation.result.status is ValidationStatus.PASS else 1
    command = run_command(
        observation.check_argv,
        expected_exit_codes=frozenset({expected_exit}),
        step_title="Reproduce result through the public project-state CLI",
        attach_success=True,
    )
    observed = parse_strict_json(command.stdout.encode("utf-8"))
    assert observed == observation.result.as_dict(), (
        "public CLI result diverged from the in-process validation result"
    )


def assert_cli_exit_mismatch_rejected(observation: ValidationObservation) -> None:
    with step_context("Verify public CLI exit/result mismatch is rejected"):
        try:
            _reproduce_validation(observation)
        except CommandExitError as error:
            expected_exit = (
                0 if observation.result.status is ValidationStatus.PASS else 1
            )
            assert error.exit_code != expected_exit, (
                f"expected CLI exit mismatch, got expected exit code {error.exit_code}"
            )
            return
        raise AssertionError("CLI exit/result mismatch was accepted")


def assert_command_evidence_policy(
    result: CommandResult,
    secret_canary: str,
    *,
    expected_command_fragments: tuple[str, ...],
    expected_stderr_fragments: tuple[str, ...],
) -> None:
    with step_context("Verify complete command evidence safety and diagnostic value"):
        assert "[TRUNCATED " in result.stdout, (
            "expected oversized command output to carry an explicit truncation marker"
        )
        assert REDACTION_MARKER in result.stdout, (
            "expected sensitive command output to carry an explicit redaction marker"
        )
        assert REDACTION_MARKER in result.stderr, (
            "expected sensitive command error output to carry a redaction marker"
        )
        assert REDACTION_MARKER in result.rendered_command, (
            "expected sensitive command argument to carry a redaction marker"
        )
        for label, value in (
            ("rendered command", result.rendered_command),
            ("stdout", result.stdout),
            ("stderr", result.stderr),
        ):
            assert secret_canary not in value, (
                f"synthetic secret canary survived in {label} evidence"
            )
        _assert_fragments_in_order(
            result.rendered_command,
            expected_command_fragments,
            "rendered command",
        )
        _assert_fragments_in_order(
            result.stderr,
            expected_stderr_fragments,
            "stderr",
        )


def assert_command_grammar(
    rendered_cases: tuple[tuple[str, str, str | None], ...],
    secret_canary: str,
) -> None:
    with step_context("Verify the complete supported secret grammar"):
        for label, rendered, preserved in rendered_cases:
            assert secret_canary not in rendered, (
                f"synthetic secret canary survived grammar case {label}: {rendered}"
            )
            assert REDACTION_MARKER in rendered, (
                f"grammar case {label} did not expose a redaction marker: {rendered}"
            )
            if preserved is not None:
                assert preserved in rendered, (
                    f"grammar case {label} lost useful key context {preserved!r}: "
                    f"{rendered}"
                )


def assert_command_failure_evidence(
    argv: tuple[str, ...],
    secret_canary: str,
) -> None:
    with step_context("Verify failed-command evidence uses only safe diagnostics"):
        try:
            run_command(
                argv,
                step_title="Run an expected command failure with a secret argument",
                attach_success=True,
            )
        except CommandExitError as error:
            assert error.exit_code != 0, (
                f"expected a nonzero command failure, got {error.exit_code}"
            )
            assert secret_canary not in error.rendered_command, (
                "synthetic secret canary survived in failed-command presentation"
            )
            assert secret_canary not in error.diagnostic, (
                "synthetic secret canary survived in failed-command diagnostic"
            )
            assert REDACTION_MARKER in error.rendered_command, (
                "failed-command presentation lacks an explicit redaction marker"
            )
            return
        raise AssertionError("expected command failure was accepted")


def _assert_fragments_in_order(
    value: str,
    fragments: tuple[str, ...],
    label: str,
) -> None:
    previous = -1
    for fragment in fragments:
        observed = value.find(fragment, previous + 1)
        assert observed > previous, (
            f"expected {fragment!r} after offset {previous} in {label}: {value}"
        )
        previous = observed


def _findings(source: FindingSource) -> Collection[Finding]:
    if isinstance(source, ValidationObservation):
        _reproduce_validation(source)
        return source.result.findings
    return source


def assert_findings_equal(
    actual: FindingSource,
    expected: Collection[Finding],
) -> None:
    with step_context("Verify exact stable finding set"):
        findings = _findings(actual)
        attach_json(
            "expected and observed findings",
            {
                "expected": [finding.as_dict() for finding in expected],
                "observed": [finding.as_dict() for finding in findings],
            },
        )
        assert set(findings) == set(expected), (
            f"expected findings {_finding_labels(expected)}, "
            f"got {_finding_labels(findings)}"
        )


def assert_has_finding(
    actual: FindingSource,
    expected: Finding,
    *,
    evidence_input: JSONValue | None = None,
    evidence_output: JSONValue | None = None,
) -> None:
    with step_context(f"Verify finding {expected.code.value} at {expected.context}"):
        findings = _findings(actual)
        if (evidence_input is None) != (evidence_output is None):
            raise ValueError("verification input and output evidence must be paired")
        if evidence_input is not None and evidence_output is not None:
            attach_json("review verification input", evidence_input)
            attach_json("review verification output", evidence_output)
        assert expected in findings, (
            f"expected finding {expected.code.value}:{expected.context}, "
            f"got {_finding_labels(findings)}"
        )


def assert_validation_summary(
    observation: ValidationObservation,
    *,
    total: int,
    truncated: bool,
) -> None:
    with step_context("Verify bounded finding summary"):
        _reproduce_validation(observation)
        assert observation.result.total_findings == total, (
            f"expected total_findings={total}, got {observation.result.total_findings}"
        )
        assert observation.result.truncated is truncated, (
            f"expected truncated={truncated}, got {observation.result.truncated}"
        )


def assert_validation_passes(result: ValidationResult) -> None:
    with step_context("Verify candidate validation passes without truncation"):
        assert result.total_findings == 0, (
            f"expected PASS with no findings, got {_finding_labels(result.findings)}"
        )
        assert not result.truncated, "expected an untruncated PASS result"


def assert_publication_status(
    result: PublicationResult,
    expected: PublicationStatus,
) -> None:
    with step_context(f"Verify publication outcome is {expected.value}"):
        assert result.result is expected, (
            f"expected publication status {expected.value}, got {result.result.value}"
        )


def assert_equal[T](
    actual: T,
    expected: T,
    label: str,
    *,
    observation: ValidationObservation | None = None,
) -> None:
    with step_context(f"Verify {label}"):
        if observation is not None:
            _reproduce_validation(observation)
        assert actual == expected, f"expected {label}={expected!r}, got {actual!r}"


def assert_true(value: bool, label: str) -> None:
    with step_context(f"Verify {label}"):
        assert value, f"expected {label} to be true"
