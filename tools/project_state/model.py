from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

type JSONScalar = bool | int | str | None
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]

JSONStrings = Annotated[tuple[StrictStr, ...], Field(strict=False)]
type ModelTuple[T] = Annotated[tuple[T, ...], Field(strict=False)]


class FindingCode(StrEnum):
    CONTRADICTION = "CONTRADICTION"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    INVALID_ARTIFACT = "INVALID_ARTIFACT"
    INVALID_BYTES = "INVALID_BYTES"
    INVALID_CHANGE = "INVALID_CHANGE"
    INVALID_INTEGRATOR = "INVALID_INTEGRATOR"
    INVALID_JSON = "INVALID_JSON"
    INVALID_NEXT_ACTION = "INVALID_NEXT_ACTION"
    INVALID_PATH = "INVALID_PATH"
    MISSING_REFERENCE = "MISSING_REFERENCE"
    NON_CANONICAL_STATE = "NON_CANONICAL_STATE"
    PROJECTION_MISMATCH = "PROJECTION_MISMATCH"
    REVIEW_ASSIGNMENT_MISMATCH = "REVIEW_ASSIGNMENT_MISMATCH"
    REVIEW_TARGET_MISMATCH = "REVIEW_TARGET_MISMATCH"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
    SHA_MISMATCH = "SHA_MISMATCH"
    UNRESOLVABLE_REFERENCE = "UNRESOLVABLE_REFERENCE"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"


class ValidationStatus(StrEnum):
    PASS = "PASS"
    STATE_DEFECT = "STATE_DEFECT"


class PublicationStatus(StrEnum):
    INVALID_CANDIDATE = "INVALID_CANDIDATE"
    PASS = "PASS"
    STALE_PREIMAGE = "STALE_PREIMAGE"
    STATE_DEFECT = "STATE_DEFECT"


@dataclass(frozen=True, slots=True)
class Finding:
    code: FindingCode
    context: str
    detail: str = field(default="", compare=False, hash=False)

    def as_dict(self) -> dict[str, JSONValue]:
        result: dict[str, JSONValue] = {
            "code": self.code.value,
            "context": self.context,
        }
        if self.detail:
            result["detail"] = self.detail
        return result


@dataclass(frozen=True, slots=True)
class ValidationResult:
    findings: frozenset[Finding]
    total_findings: int
    truncated: bool

    @property
    def status(self) -> ValidationStatus:
        return (
            ValidationStatus.STATE_DEFECT
            if self.total_findings
            else ValidationStatus.PASS
        )

    def as_dict(self) -> dict[str, JSONValue]:
        findings = sorted(
            self.findings,
            key=lambda finding: (finding.code.value, finding.context),
        )
        return {
            "findings": [finding.as_dict() for finding in findings],
            "result": self.status.value,
            "total_findings": self.total_findings,
            "truncated": self.truncated,
        }


class FindingCollector:
    __slots__ = ("_findings",)

    def __init__(self) -> None:
        self._findings: dict[Finding, Finding] = {}

    def add(self, code: FindingCode, context: str, detail: str = "") -> None:
        finding = Finding(code, context, detail)
        current = self._findings.get(finding)
        if current is None or finding.detail < current.detail:
            self._findings[finding] = finding

    def extend(self, findings: frozenset[Finding]) -> None:
        for finding in findings:
            self.add(finding.code, finding.context, finding.detail)

    def result(self, max_findings: int | None = None) -> ValidationResult:
        if max_findings is not None and max_findings < 1:
            raise ValueError("max_findings must be positive")
        ordered = sorted(
            self._findings.values(),
            key=lambda finding: (finding.code.value, finding.context),
        )
        total = len(ordered)
        visible = ordered if max_findings is None else ordered[:max_findings]
        return ValidationResult(frozenset(visible), total, len(visible) < total)

    def __bool__(self) -> bool:
        return bool(self._findings)


class ExternalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AcceptedSourceBaseline(ExternalModel):
    git_commit: StrictStr
    source_artifact_id: StrictStr | None = None


class ActiveChange(ExternalModel):
    change_id: StrictStr
    contract_ref: StrictStr
    required_artifact_ids: JSONStrings


class Integrator(ExternalModel):
    assignee_ref: StrictStr
    assignment_ref: StrictStr


class OpenDecisions(ExternalModel):
    product: JSONStrings
    technical: JSONStrings

    @property
    def has_any(self) -> bool:
        return bool(self.product or self.technical)


class OpenBlocker(ExternalModel):
    blocker_id: StrictStr
    blocker_ref: StrictStr
    blocks_change_ids: JSONStrings


class AcceptedArtifact(ExternalModel):
    artifact_id: StrictStr
    kind: StrictStr
    manifest_ref: StrictStr
    sha256: StrictStr


class CoordinationState(ExternalModel):
    accepted_artifacts: ModelTuple[AcceptedArtifact]
    accepted_source_baseline: AcceptedSourceBaseline
    active_changes: ModelTuple[ActiveChange]
    enforcement_matrix_ref: StrictStr
    integrator: Integrator
    next_action_change_ids: JSONStrings
    open_blockers: ModelTuple[OpenBlocker]
    open_decisions: OpenDecisions
    product_phase_ref: StrictStr
    production_gate_ref: StrictStr
    project_id: StrictStr
    role_registry_ref: StrictStr
    schema_version: StrictStr


class IntegratorAssignment(ExternalModel):
    assignment_id: StrictStr
    assignment_kind: Literal["integrator"]
    assignee_ref: StrictStr
    superseded: StrictBool


class ArtifactManifest(ExternalModel):
    artifact_id: StrictStr
    artifact_ref: StrictStr
    kind: StrictStr
    sha256: StrictStr
    source_git_commit: StrictStr | None = None


@dataclass(frozen=True, slots=True)
class PreparedCandidate:
    expected_coordination_parent_commit: str
    candidate_coordination_commit: str
    candidate_state_sha256: str


@dataclass(frozen=True, slots=True)
class CandidateDefect:
    expected_coordination_parent_commit: str
    candidate_state_sha256: str
    findings: frozenset[Finding]


@dataclass(frozen=True, slots=True)
class PublicationResult:
    result: PublicationStatus
    expected_coordination_parent_commit: str
    expected_source_state_sha256: str
    candidate_coordination_commit: str | None = None
    candidate_state_sha256: str | None = None
    findings: frozenset[Finding] = frozenset()

    def as_dict(self) -> dict[str, JSONValue]:
        findings = sorted(
            self.findings,
            key=lambda finding: (finding.code.value, finding.context),
        )
        return {
            "candidate_coordination_commit": self.candidate_coordination_commit,
            "candidate_state_sha256": self.candidate_state_sha256,
            "expected_coordination_parent_commit": self.expected_coordination_parent_commit,
            "expected_source_state_sha256": self.expected_source_state_sha256,
            "findings": [finding.as_dict() for finding in findings],
            "result": self.result.value,
        }
