from dataclasses import dataclass

from tools.project_state.artifact_validation import validate_artifacts_and_baseline
from tools.project_state.decoding import decode_parsed_state, parse_state_bytes
from tools.project_state.model import (
    CoordinationState,
    Finding,
    FindingCode,
    FindingCollector,
    ValidationResult,
)
from tools.project_state.pointer import json_pointer
from tools.project_state.projection import render_projection
from tools.project_state.reference_validation import (
    ReferenceFacts,
    validate_references,
)
from tools.project_state.repository import TreeReader

STATE_PATH = "docs/project/state.json"
SCHEMA_PATH = "docs/project/state.schema.json"
PROJECTION_PATH = "docs/project/CURRENT_STATE.md"


@dataclass(frozen=True, slots=True)
class CandidateValidation:
    result: ValidationResult
    state: CoordinationState | None


def _read_candidate_file(
    tree: TreeReader,
    path: str,
    context: str,
    code: FindingCode,
    findings: FindingCollector,
) -> bytes | None:
    mode = tree.mode(path)
    if mode != "100644":
        findings.add(code, context, f"missing regular candidate file: {path}")
        return None
    content = tree.read(path)
    if content is None:
        findings.add(code, context, f"unreadable candidate file: {path}")
    return content


def _require_order(
    values: tuple[str, ...],
    context: str,
    findings: FindingCollector,
    *,
    unique: bool = False,
) -> None:
    expected = tuple(sorted(set(values))) if unique else tuple(sorted(values))
    if values != expected:
        suffix = " uniquely" if unique else ""
        findings.add(
            FindingCode.NON_CANONICAL_STATE,
            context,
            f"set-like array must be sorted{suffix}",
        )


def _validate_set_order(state: CoordinationState, findings: FindingCollector) -> None:
    for values, context in (
        (
            tuple(item.artifact_id for item in state.accepted_artifacts),
            json_pointer("accepted_artifacts"),
        ),
        (
            tuple(item.change_id for item in state.active_changes),
            json_pointer("active_changes"),
        ),
        (
            tuple(item.blocker_id for item in state.open_blockers),
            json_pointer("open_blockers"),
        ),
        (state.next_action_change_ids, json_pointer("next_action_change_ids")),
        (state.open_decisions.product, json_pointer("open_decisions", "product")),
        (state.open_decisions.technical, json_pointer("open_decisions", "technical")),
    ):
        _require_order(values, context, findings, unique=True)
    for change in state.active_changes:
        _require_order(
            change.required_artifact_ids,
            json_pointer("active_changes", change.change_id, "required_artifact_ids"),
            findings,
        )
    for blocker in state.open_blockers:
        _require_order(
            blocker.blocks_change_ids,
            json_pointer("open_blockers", blocker.blocker_id, "blocks_change_ids"),
            findings,
        )


def _validate_next_actions(
    state: CoordinationState,
    references: ReferenceFacts,
    findings: FindingCollector,
) -> None:
    for change_id in state.next_action_change_ids:
        context = json_pointer("next_action_change_ids", change_id)
        if change_id not in references.change_ids:
            findings.add(
                FindingCode.INVALID_NEXT_ACTION, context, "Change is not active"
            )
        elif change_id in references.blocked_change_ids:
            findings.add(FindingCode.INVALID_NEXT_ACTION, context, "Change is blocked")
        elif change_id not in references.actionable_change_ids:
            findings.add(
                FindingCode.INVALID_NEXT_ACTION,
                context,
                "Change contract is not actionable",
            )
    if not state.next_action_change_ids:
        unexplained = (
            references.actionable_change_ids
            - references.blocked_change_ids
            - references.decision_explanations
        )
        if unexplained or (
            not references.actionable_change_ids
            and not state.open_blockers
            and not state.open_decisions.has_any
        ):
            detail = ", ".join(sorted(unexplained)) or "no authoritative explanation"
            findings.add(
                FindingCode.INVALID_NEXT_ACTION,
                json_pointer("next_action_change_ids"),
                f"actionable Changes lack a blocker or decision: {detail}",
            )


def _validate_semantics(
    state: CoordinationState,
    tree: TreeReader,
) -> frozenset[Finding]:
    findings = FindingCollector()
    _validate_set_order(state, findings)
    references = validate_references(state, tree, findings)
    validate_artifacts_and_baseline(state, tree, findings)
    _validate_next_actions(state, references, findings)
    return findings.result().findings


def prevalidate_state(
    raw: bytes,
    tree: TreeReader,
    max_findings: int | None = None,
) -> CandidateValidation:
    findings = FindingCollector()
    parsed = parse_state_bytes(raw)
    findings.extend(parsed.findings)
    if parsed.value is None:
        return CandidateValidation(findings.result(max_findings), None)
    schema = _read_candidate_file(
        tree,
        SCHEMA_PATH,
        json_pointer("schema"),
        FindingCode.SCHEMA_VIOLATION,
        findings,
    )
    if schema is None:
        return CandidateValidation(findings.result(max_findings), None)
    decoded = decode_parsed_state(raw, parsed.value, schema)
    findings.extend(decoded.findings)
    if findings:
        return CandidateValidation(findings.result(max_findings), None)
    if decoded.state is None:
        raise RuntimeError("decoder returned neither state nor findings")
    findings.extend(_validate_semantics(decoded.state, tree))
    return CandidateValidation(findings.result(max_findings), decoded.state)


def validate_candidate(
    tree: TreeReader,
    max_findings: int | None = None,
) -> CandidateValidation:
    findings = FindingCollector()
    raw = _read_candidate_file(
        tree,
        STATE_PATH,
        json_pointer("state"),
        FindingCode.MISSING_REFERENCE,
        findings,
    )
    if raw is None:
        return CandidateValidation(findings.result(max_findings), None)
    state_validation = prevalidate_state(raw, tree, max_findings)
    if state_validation.result.total_findings:
        return state_validation
    state = state_validation.state
    if state is None:
        raise RuntimeError("state validation passed without a decoded state")
    projection = _read_candidate_file(
        tree,
        PROJECTION_PATH,
        json_pointer("projection"),
        FindingCode.PROJECTION_MISMATCH,
        findings,
    )
    if projection is None:
        return CandidateValidation(findings.result(max_findings), state)
    if projection != render_projection(state):
        findings.add(
            FindingCode.PROJECTION_MISMATCH,
            json_pointer("projection"),
            "CURRENT_STATE.md was not generated from this candidate",
        )
    return CandidateValidation(findings.result(max_findings), state)


def render_candidate(tree: TreeReader) -> bytes | ValidationResult:
    findings = FindingCollector()
    raw = _read_candidate_file(
        tree,
        STATE_PATH,
        json_pointer("state"),
        FindingCode.MISSING_REFERENCE,
        findings,
    )
    if raw is None:
        return findings.result()
    checked = prevalidate_state(raw, tree)
    if checked.result.total_findings:
        return checked.result
    if checked.state is None:
        raise RuntimeError("prevalidation passed without a decoded state")
    return render_projection(checked.state)
