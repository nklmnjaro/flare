from dataclasses import replace

from tools.project_state.model import Finding, FindingCode, JSONValue
from tools.project_state.review import (
    ReviewerAssignment,
    ReviewResponse,
    make_review_target,
    verify_review_response,
)
from tools.quality.tests.project_state.assertions import assert_has_finding
from tools.quality.tests.project_state.reporting import (
    Area,
    Scenario,
    step_context,
)

ASSIGNMENT = ReviewerAssignment(
    assignment_id="qa1-a1",
    reviewer_role="qa1",
    scope=frozenset({"publication", "validation"}),
)


def _review_input(
    payload: JSONValue,
    assignment: ReviewerAssignment,
    response: ReviewResponse,
) -> dict[str, JSONValue]:
    target = response.target
    scope: list[JSONValue] = []
    scope.extend(sorted(assignment.scope))
    return {
        "current_assignment": {
            "assignment_id": assignment.assignment_id,
            "reviewer_role": assignment.reviewer_role,
            "scope": scope,
        },
        "expected_payload": payload,
        "response": {
            "reviewer_role": response.reviewer_role,
            "target": {
                "assignment_sha256": target.assignment_sha256,
                "reviewer_role": target.reviewer_role,
                "semantic_payload_sha256": target.semantic_payload_sha256,
                "target_id": target.target_id,
            },
        },
    }


def _review_output(findings: frozenset[Finding]) -> dict[str, JSONValue]:
    return {"observed_findings": [finding.as_dict() for finding in findings]}


def verify_a1_n31_wrong_payload() -> None:
    assignment = ASSIGNMENT
    wrong_payload: JSONValue = {"commit": "wrong"}
    expected_payload: JSONValue = {"commit": "expected"}
    response = ReviewResponse(
        reviewer_role="qa1",
        target=make_review_target(wrong_payload, assignment),
    )
    findings = verify_review_response(expected_payload, assignment, response)
    assert_has_finding(
        findings,
        Finding(FindingCode.REVIEW_TARGET_MISMATCH, "$/review/semantic_payload"),
        evidence_input=_review_input(expected_payload, assignment, response),
        evidence_output=_review_output(findings),
    )
    with step_context("Independently reject a forged review target ID"):
        forged = replace(response.target, target_id="0" * 64)
        forged_response = replace(response, target=forged)
        forged_findings = verify_review_response(
            expected_payload,
            assignment,
            forged_response,
        )
        assert_has_finding(
            forged_findings,
            Finding(FindingCode.REVIEW_TARGET_MISMATCH, "$/review/target_id"),
            evidence_input=_review_input(
                expected_payload,
                assignment,
                forged_response,
            ),
            evidence_output=_review_output(forged_findings),
        )


def verify_a1_n32_stale_assignment(stale_field: str) -> None:
    payload: JSONValue = {"commit": "candidate"}
    current = ASSIGNMENT
    if stale_field == "assignment-id":
        stale = replace(current, assignment_id="qa1-old")
    elif stale_field == "scope":
        stale = replace(current, scope=frozenset({"validation"}))
    else:
        raise ValueError(f"unsupported stale assignment field: {stale_field}")
    response = ReviewResponse(
        reviewer_role="qa1",
        target=make_review_target(payload, stale),
    )
    findings = verify_review_response(payload, current, response)
    assert_has_finding(
        findings,
        Finding(FindingCode.REVIEW_ASSIGNMENT_MISMATCH, "$/review/assignment"),
        evidence_input=_review_input(payload, current, response),
        evidence_output=_review_output(findings),
    )
    with step_context("Independently reject the wrong responding reviewer role"):
        wrong_role_response = replace(response, reviewer_role="linter")
        wrong_role_findings = verify_review_response(
            payload,
            current,
            wrong_role_response,
        )
        assert_has_finding(
            wrong_role_findings,
            Finding(
                FindingCode.REVIEW_ASSIGNMENT_MISMATCH,
                "$/review/responding_reviewer_role",
            ),
            evidence_input=_review_input(
                payload,
                current,
                wrong_role_response,
            ),
            evidence_output=_review_output(wrong_role_findings),
        )


REVIEW_SCENARIOS: tuple[Scenario[None], ...] = (
    Scenario(
        "A1-N31",
        "Reject wrong semantic payload",
        Area.REVIEW,
        lambda _: verify_a1_n31_wrong_payload(),
    ),
    Scenario(
        "A1-N32",
        "Reject stale assignment ID",
        Area.REVIEW,
        lambda _: verify_a1_n32_stale_assignment("assignment-id"),
    ),
    Scenario(
        "A1-N32",
        "Reject stale assignment scope",
        Area.REVIEW,
        lambda _: verify_a1_n32_stale_assignment("scope"),
    ),
)
