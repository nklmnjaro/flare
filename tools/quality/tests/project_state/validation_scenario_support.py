from tools.project_state.model import Finding, FindingCode
from tools.project_state.pointer import json_pointer
from tools.quality.tests.project_state.assertions import (
    assert_findings_equal,
    assert_has_finding,
)
from tools.quality.tests.project_state.command_evidence import ValidationObservation
from tools.quality.tests.project_state.support import CHANGE_ID

CHANGE_CONTEXT = json_pointer("active_changes", CHANGE_ID, "contract_ref")


def finding(code: FindingCode, *segments: str) -> Finding:
    return Finding(code, json_pointer(*segments))


def verify_finding(
    result: ValidationObservation,
    code: FindingCode,
    *segments: str,
) -> None:
    assert_has_finding(result, finding(code, *segments))


def verify_finding_at(
    result: ValidationObservation,
    code: FindingCode,
    context: str,
) -> None:
    assert_has_finding(result, Finding(code, context))


def verify_only(
    result: ValidationObservation,
    *findings: Finding,
) -> None:
    assert_findings_equal(result, set(findings))
