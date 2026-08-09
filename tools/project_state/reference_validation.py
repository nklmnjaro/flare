import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from tools.project_state.authority import (
    ACTIVE_CHANGE_STATUS,
    ENFORCEMENT_MATRIX_REF,
    PRODUCT_PHASE_REF,
    PRODUCTION_GATE_REF,
    ROLE_REGISTRY_REF,
    markdown_metadata,
    parse_blocker,
    parse_change_contract,
    parse_decision,
    parse_integrator_assignment,
    resolve_principals,
)
from tools.project_state.model import (
    ActiveChange,
    CoordinationState,
    FindingCode,
    FindingCollector,
    OpenBlocker,
)
from tools.project_state.pointer import json_pointer
from tools.project_state.repository import TreeReader


@dataclass(frozen=True, slots=True)
class ReferenceFacts:
    actionable_change_ids: frozenset[str]
    blocked_change_ids: frozenset[str]
    change_ids: frozenset[str]
    decision_explanations: frozenset[str]


def _valid_repo_path(value: str) -> bool:
    if (
        not value
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return False
    path = PurePosixPath(value)
    return (
        path.as_posix() == value
        and not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _read_reference(
    tree: TreeReader,
    value: str,
    context: str,
    findings: FindingCollector,
) -> bytes | None:
    if not _valid_repo_path(value):
        findings.add(FindingCode.INVALID_PATH, context, value)
        return None
    mode = tree.mode(value)
    if mode is None:
        findings.add(FindingCode.UNRESOLVABLE_REFERENCE, context, value)
        return None
    if mode == "120000":
        findings.add(
            FindingCode.UNRESOLVABLE_REFERENCE,
            context,
            "symlink target is forbidden",
        )
        return None
    if mode not in {"100644", "100755"}:
        findings.add(
            FindingCode.UNRESOLVABLE_REFERENCE,
            context,
            f"unsupported Git mode {mode}",
        )
        return None
    content = tree.read(value)
    if content is None:
        findings.add(FindingCode.UNRESOLVABLE_REFERENCE, context, value)
    return content


def read_reference(
    tree: TreeReader,
    value: str,
    context: str,
    findings: FindingCollector,
) -> bytes | None:
    """Read one validated repository reference for another validation module."""
    return _read_reference(tree, value, context, findings)


def _exact_reference(
    tree: TreeReader,
    actual: str,
    expected: str,
    context: str,
    findings: FindingCollector,
) -> bytes | None:
    if not _valid_repo_path(actual):
        findings.add(FindingCode.INVALID_PATH, context, actual)
        return None
    if actual != expected:
        findings.add(
            FindingCode.UNRESOLVABLE_REFERENCE,
            context,
            f"expected accepted source {expected}",
        )
        return None
    return _read_reference(tree, actual, context, findings)


def _validate_fixed_references(
    state: CoordinationState,
    tree: TreeReader,
    findings: FindingCollector,
) -> dict[str, bytes | None]:
    specifications = (
        ("product_phase_ref", state.product_phase_ref, PRODUCT_PHASE_REF),
        ("production_gate_ref", state.production_gate_ref, PRODUCTION_GATE_REF),
        ("role_registry_ref", state.role_registry_ref, ROLE_REGISTRY_REF),
        (
            "enforcement_matrix_ref",
            state.enforcement_matrix_ref,
            ENFORCEMENT_MATRIX_REF,
        ),
    )
    refs = {
        field: _exact_reference(tree, actual, expected, json_pointer(field), findings)
        for field, actual, expected in specifications
    }
    enforcement = refs["enforcement_matrix_ref"]
    metadata = markdown_metadata(enforcement) if enforcement is not None else None
    if metadata is not None and (
        metadata.get("document_id") != "FLARE-ENFORCEMENT-MATRIX-0001"
        or metadata.get("status")
        != "INITIAL TRACEABILITY CLASSIFICATION FOR CURRENT SCAFFOLD"
    ):
        findings.add(
            FindingCode.UNRESOLVABLE_REFERENCE,
            json_pointer("enforcement_matrix_ref"),
            "wrong enforcement matrix identity or status",
        )
    elif enforcement is not None and metadata is None:
        findings.add(
            FindingCode.UNRESOLVABLE_REFERENCE,
            json_pointer("enforcement_matrix_ref"),
            "enforcement matrix metadata is invalid",
        )
    return refs


def _validate_integrator(
    state: CoordinationState,
    tree: TreeReader,
    refs: dict[str, bytes | None],
    findings: FindingCollector,
) -> None:
    registry = refs["role_registry_ref"]
    principals = (
        resolve_principals(registry, state.integrator.assignee_ref)
        if registry is not None
        else None
    )
    if principals is None or len(principals) != 1:
        count = "unresolved" if principals is None else str(len(principals))
        findings.add(
            FindingCode.INVALID_INTEGRATOR,
            json_pointer("integrator", "assignee_ref"),
            f"resolved current-principal count is {count}",
        )

    context = json_pointer("integrator", "assignment_ref")
    raw = _read_reference(tree, state.integrator.assignment_ref, context, findings)
    assignment = parse_integrator_assignment(raw) if raw is not None else None
    if (
        assignment is None
        or assignment.superseded
        or assignment.assignee_ref != state.integrator.assignee_ref
    ):
        findings.add(
            FindingCode.INVALID_INTEGRATOR,
            context,
            "explicit current Integrator assignment does not match assignee",
        )


def _validate_changes(
    changes: tuple[ActiveChange, ...],
    tree: TreeReader,
    findings: FindingCollector,
) -> tuple[set[str], set[str]]:
    change_ids = {change.change_id for change in changes}
    actionable: set[str] = set()
    for change in changes:
        context = json_pointer("active_changes", change.change_id, "contract_ref")
        expected_ref = f"docs/engineering/changes/{change.change_id}.md"
        if change.contract_ref != expected_ref:
            findings.add(
                FindingCode.INVALID_CHANGE,
                context,
                f"expected accepted Change source {expected_ref}",
            )
            continue
        raw = _read_reference(tree, change.contract_ref, context, findings)
        contract = parse_change_contract(raw) if raw is not None else None
        if (
            contract is None
            or contract.change_id != change.change_id
            or contract.status != ACTIVE_CHANGE_STATUS
        ):
            findings.add(
                FindingCode.INVALID_CHANGE,
                context,
                "wrong Change identity or non-active lifecycle",
            )
            continue
        if not contract.implementation_authorized:
            findings.add(
                FindingCode.INVALID_CHANGE,
                context,
                "implementation is not explicitly authorized",
            )
            continue
        actionable.add(change.change_id)
    return change_ids, actionable


def _validate_decisions(
    state: CoordinationState,
    tree: TreeReader,
    change_ids: set[str],
    findings: FindingCollector,
) -> set[str]:
    explained: set[str] = set()
    groups = (
        ("product", state.open_decisions.product),
        ("technical", state.open_decisions.technical),
    )
    for kind, references in groups:
        for reference in references:
            context = json_pointer("open_decisions", kind, reference)
            raw = _read_reference(tree, reference, context, findings)
            decision = parse_decision(raw) if raw is not None else None
            if decision is None or decision.status not in {"OPEN", "PENDING"}:
                findings.add(
                    FindingCode.UNRESOLVABLE_REFERENCE,
                    context,
                    "decision identity is missing or decision is not open",
                )
                continue
            unknown = decision.blocks_change_ids - change_ids
            for change_id in unknown:
                findings.add(
                    FindingCode.INVALID_CHANGE,
                    json_pointer("open_decisions", kind, reference, change_id),
                    "decision explains a Change that is not active",
                )
            explained.update(decision.blocks_change_ids & change_ids)
    return explained


def _validate_blockers(
    blockers: tuple[OpenBlocker, ...],
    tree: TreeReader,
    change_ids: set[str],
    findings: FindingCollector,
) -> set[str]:
    blocked: set[str] = set()
    for blocker in blockers:
        context = json_pointer("open_blockers", blocker.blocker_id, "blocker_ref")
        raw = _read_reference(tree, blocker.blocker_ref, context, findings)
        authoritative = parse_blocker(raw) if raw is not None else None
        is_current = (
            authoritative is not None
            and authoritative.blocker_id == blocker.blocker_id
            and authoritative.status == "OPEN"
        )
        if not is_current:
            findings.add(
                FindingCode.UNRESOLVABLE_REFERENCE,
                context,
                "wrong blocker identity or blocker is not open",
            )
        for blocked_id in blocker.blocks_change_ids:
            context = json_pointer(
                "open_blockers",
                blocker.blocker_id,
                "blocks_change_ids",
                blocked_id,
            )
            if blocked_id not in change_ids:
                findings.add(
                    FindingCode.INVALID_CHANGE,
                    context,
                    "blocked Change is not active",
                )
            elif is_current:
                blocked.add(blocked_id)
    return blocked


def validate_references(
    state: CoordinationState,
    tree: TreeReader,
    findings: FindingCollector,
) -> ReferenceFacts:
    refs = _validate_fixed_references(state, tree, findings)
    _validate_integrator(state, tree, refs, findings)
    change_ids, actionable = _validate_changes(state.active_changes, tree, findings)
    decisions = _validate_decisions(state, tree, change_ids, findings)
    blocked = _validate_blockers(state.open_blockers, tree, change_ids, findings)
    return ReferenceFacts(
        actionable_change_ids=frozenset(actionable),
        blocked_change_ids=frozenset(blocked),
        change_ids=frozenset(change_ids),
        decision_explanations=frozenset(decisions),
    )
