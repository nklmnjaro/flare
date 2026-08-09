import tomllib
from dataclasses import dataclass
from datetime import date, datetime, time

from pydantic import ValidationError

from tools.project_state.json_codec import (
    DuplicateKeyError,
    StrictJSONError,
    parse_strict_json,
)
from tools.project_state.model import IntegratorAssignment

PRODUCT_PHASE_REF = "docs/onboarding/START-HERE.md"
PRODUCTION_GATE_REF = "AGENTS.md"
ROLE_REGISTRY_REF = "tools/platform/team_dispatch/config.toml"
ENFORCEMENT_MATRIX_REF = (
    "docs/engineering/governance/rc2/FLARE_ENFORCEMENT_MATRIX_v0.2_20260807.md"
)
ACTIVE_CHANGE_STATUS = "ACCEPTED / READY FOR BOUNDED CODE"

type TOMLScalar = bool | int | float | str | date | datetime | time | None
type TOMLValue = TOMLScalar | list[TOMLValue] | dict[str, TOMLValue]


@dataclass(frozen=True, slots=True)
class ChangeContract:
    change_id: str
    status: str
    implementation_authorized: bool


@dataclass(frozen=True, slots=True)
class ReferencedDecision:
    decision_id: str
    status: str
    blocks_change_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class ReferencedBlocker:
    blocker_id: str
    status: str


def _decode_utf8(raw: bytes) -> str | None:
    try:
        return raw.decode("utf-8", "strict")
    except UnicodeDecodeError:
        return None


def _store_field(fields: dict[str, str], key: str, value: str) -> bool:
    normalized = key.strip().lower().replace(" ", "_")
    if not normalized or normalized in fields:
        return False
    fields[normalized] = value.strip().strip('"').strip("`")
    return True


def markdown_metadata(raw: bytes) -> dict[str, str] | None:
    text = _decode_utf8(raw)
    if text is None:
        return None
    fields: dict[str, str] = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    closed = False
    for line in lines[1:]:
        if line.strip() == "---":
            closed = True
            break
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator or not value.strip() or not _store_field(fields, key, value):
            return None
    return fields if closed and fields else None


def parse_change_contract(raw: bytes) -> ChangeContract | None:
    metadata = markdown_metadata(raw)
    if metadata is None:
        return None
    change_id = metadata.get("change_id")
    status = metadata.get("status")
    authorization = metadata.get("implementation_authorization")
    if change_id is None or status is None or authorization is None:
        return None
    return ChangeContract(change_id, status, authorization == "AUTHORIZED")


def parse_integrator_assignment(raw: bytes) -> IntegratorAssignment | None:
    try:
        value = parse_strict_json(raw)
        return IntegratorAssignment.model_validate(value)
    except DuplicateKeyError, StrictJSONError, ValidationError:
        return None


def _toml_table(value: TOMLValue | None) -> dict[str, TOMLValue] | None:
    return value if isinstance(value, dict) else None


def resolve_principals(raw: bytes, assignee_ref: str) -> tuple[str, ...] | None:
    text = _decode_utf8(raw)
    if text is None:
        return None
    try:
        registry: dict[str, TOMLValue] = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    roles = _toml_table(registry.get("roles"))
    role = _toml_table(roles.get(assignee_ref)) if roles is not None else None
    if role is None:
        return ()
    principal_refs = role.get("principal_refs")
    principals = _toml_table(registry.get("principals"))
    if not isinstance(principal_refs, list) or principals is None:
        return ()
    if not all(
        isinstance(principal_ref, str) and principal_ref
        for principal_ref in principal_refs
    ):
        return ()
    current: list[str] = []
    for principal_ref in principal_refs:
        if not isinstance(principal_ref, str):
            return ()
        principal = _toml_table(principals.get(principal_ref))
        if (
            principal is not None
            and principal.get("status") == "current"
            and isinstance(principal.get("display"), str)
            and principal.get("display")
        ):
            current.append(principal_ref)
    return tuple(current)


def parse_decision(raw: bytes) -> ReferencedDecision | None:
    metadata = markdown_metadata(raw)
    if metadata is None:
        return None
    decision_id = metadata.get("document_id") or metadata.get("decision_id")
    status = metadata.get("status")
    if decision_id is None or status is None:
        return None
    blocked = metadata.get("blocks_change_ids", "")
    return ReferencedDecision(
        decision_id,
        status,
        frozenset(value.strip() for value in blocked.split(",") if value.strip()),
    )


def parse_blocker(raw: bytes) -> ReferencedBlocker | None:
    metadata = markdown_metadata(raw)
    if metadata is None:
        return None
    blocker_id = metadata.get("blocker_id")
    status = metadata.get("status")
    if blocker_id is None or status is None:
        return None
    return ReferencedBlocker(blocker_id, status)
