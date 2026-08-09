import hashlib
from dataclasses import dataclass

from tools.project_state.json_codec import canonical_json_bytes
from tools.project_state.model import Finding, FindingCode, FindingCollector, JSONValue
from tools.project_state.pointer import json_pointer


@dataclass(frozen=True, slots=True)
class ReviewerAssignment:
    assignment_id: str
    reviewer_role: str
    scope: frozenset[str]


@dataclass(frozen=True, slots=True)
class ReviewTarget:
    assignment_sha256: str
    reviewer_role: str
    semantic_payload_sha256: str
    target_id: str


@dataclass(frozen=True, slots=True)
class ReviewResponse:
    reviewer_role: str
    target: ReviewTarget


def _digest_json(value: JSONValue) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def make_review_target(
    payload: JSONValue,
    assignment: ReviewerAssignment,
) -> ReviewTarget:
    scope: list[JSONValue] = []
    scope.extend(sorted(assignment.scope))
    normalized_assignment: JSONValue = {
        "assignment_id": assignment.assignment_id,
        "reviewer_role": assignment.reviewer_role,
        "scope": scope,
    }
    payload_sha = _digest_json(payload)
    assignment_sha = _digest_json(normalized_assignment)
    target_identity: JSONValue = {
        "assignment_sha256": assignment_sha,
        "reviewer_role": assignment.reviewer_role,
        "semantic_payload_sha256": payload_sha,
    }
    return ReviewTarget(
        assignment_sha256=assignment_sha,
        reviewer_role=assignment.reviewer_role,
        semantic_payload_sha256=payload_sha,
        target_id=_digest_json(target_identity),
    )


def verify_review_response(
    payload: JSONValue,
    assignment: ReviewerAssignment,
    response: ReviewResponse,
) -> frozenset[Finding]:
    expected = make_review_target(payload, assignment)
    target = response.target
    findings = FindingCollector()
    if target.semantic_payload_sha256 != expected.semantic_payload_sha256:
        findings.add(
            FindingCode.REVIEW_TARGET_MISMATCH,
            json_pointer("review", "semantic_payload"),
        )
    if target.assignment_sha256 != expected.assignment_sha256:
        findings.add(
            FindingCode.REVIEW_ASSIGNMENT_MISMATCH,
            json_pointer("review", "assignment"),
        )
    if target.reviewer_role != expected.reviewer_role:
        findings.add(
            FindingCode.REVIEW_ASSIGNMENT_MISMATCH,
            json_pointer("review", "assigned_reviewer_role"),
        )
    if response.reviewer_role != assignment.reviewer_role:
        findings.add(
            FindingCode.REVIEW_ASSIGNMENT_MISMATCH,
            json_pointer("review", "responding_reviewer_role"),
        )
    if target.target_id != expected.target_id:
        findings.add(
            FindingCode.REVIEW_TARGET_MISMATCH,
            json_pointer("review", "target_id"),
        )
    return findings.result().findings
