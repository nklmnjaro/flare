import hashlib
from dataclasses import dataclass

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError

from tools.project_state.json_codec import (
    DuplicateKeyError,
    StrictJSONError,
    canonical_json_bytes,
    parse_strict_json,
)
from tools.project_state.model import (
    CoordinationState,
    Finding,
    FindingCode,
    FindingCollector,
    JSONValue,
)
from tools.project_state.pointer import json_pointer

SCHEMA_ID = "urn:flare:coordination-state:1.0"
ACCEPTED_SCHEMA_SHA256 = (
    "affe96d268e5400a866aedabfc3e8781e52403440445ce63e4154d7b627a48aa"
)
SUPPORTED_SCHEMA = "1.0"


@dataclass(frozen=True, slots=True)
class DecodedState:
    state: CoordinationState | None
    findings: frozenset[Finding]


@dataclass(frozen=True, slots=True)
class ParsedStateJSON:
    value: JSONValue | None
    findings: frozenset[Finding]


def _raw_bytes_findings(raw: bytes) -> frozenset[Finding]:
    findings = FindingCollector()
    if raw.startswith(b"\xef\xbb\xbf"):
        findings.add(FindingCode.INVALID_BYTES, "$", "UTF-8 BOM is forbidden")
    if b"\r" in raw or not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        findings.add(
            FindingCode.INVALID_BYTES,
            "$",
            "state must use LF and have exactly one trailing LF",
        )
    return findings.result().findings


def _parse_state(raw: bytes, findings: FindingCollector) -> JSONValue | None:
    try:
        return parse_strict_json(raw)
    except DuplicateKeyError as error:
        findings.add(FindingCode.DUPLICATE_KEY, "$", f"duplicate key: {error}")
    except StrictJSONError as error:
        findings.add(FindingCode.INVALID_JSON, "$", str(error))
    return None


def _parse_schema(
    raw: bytes, findings: FindingCollector
) -> dict[str, JSONValue] | None:
    if hashlib.sha256(raw).hexdigest() != ACCEPTED_SCHEMA_SHA256:
        findings.add(
            FindingCode.SCHEMA_VIOLATION,
            "$/schema",
            "candidate schema content is not the accepted immutable schema",
        )
        return None
    try:
        value = parse_strict_json(raw)
    except (DuplicateKeyError, StrictJSONError) as error:
        findings.add(FindingCode.SCHEMA_VIOLATION, "$/schema", str(error))
        return None
    if not isinstance(value, dict) or value.get("$id") != SCHEMA_ID:
        findings.add(
            FindingCode.SCHEMA_VIOLATION,
            "$/schema/$id",
            "candidate schema identity is not accepted",
        )
        return None
    return value


def _validate_schema(
    schema: dict[str, JSONValue],
    value: JSONValue,
    findings: FindingCollector,
) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        findings.add(
            FindingCode.SCHEMA_VIOLATION,
            "$/schema",
            f"invalid candidate schema: {error.message}",
        )
        return
    issues = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda issue: tuple(map(str, issue.absolute_path)),
    )
    for issue in issues:
        findings.add(
            FindingCode.SCHEMA_VIOLATION,
            json_pointer(*issue.absolute_path),
            issue.message,
        )


def _parse_model(
    value: JSONValue, findings: FindingCollector
) -> CoordinationState | None:
    try:
        return CoordinationState.model_validate(value)
    except ValidationError as error:
        for issue in error.errors(
            include_context=False,
            include_input=False,
            include_url=False,
        ):
            findings.add(
                FindingCode.SCHEMA_VIOLATION,
                json_pointer(*issue["loc"]),
                issue["msg"],
            )
    return None


def parse_state_bytes(raw: bytes) -> ParsedStateJSON:
    findings = FindingCollector()
    findings.extend(_raw_bytes_findings(raw))
    if findings:
        return ParsedStateJSON(None, findings.result().findings)

    value = _parse_state(raw, findings)
    if value is None:
        return ParsedStateJSON(None, findings.result().findings)
    return ParsedStateJSON(value, frozenset())


def decode_parsed_state(
    raw: bytes,
    value: JSONValue,
    schema_raw: bytes,
) -> DecodedState:
    findings = FindingCollector()
    schema = _parse_schema(schema_raw, findings)
    if schema is None:
        return DecodedState(None, findings.result().findings)

    _validate_schema(schema, value, findings)
    if findings:
        return DecodedState(None, findings.result().findings)

    state = _parse_model(value, findings)
    if state is None:
        return DecodedState(None, findings.result().findings)
    if state.schema_version != SUPPORTED_SCHEMA:
        findings.add(
            FindingCode.UNSUPPORTED_SCHEMA,
            "$/schema_version",
            state.schema_version,
        )
    elif canonical_json_bytes(value) != raw:
        findings.add(
            FindingCode.NON_CANONICAL_STATE,
            "$",
            "JSON bytes are not canonical",
        )
    return DecodedState(
        state if not findings else None,
        findings.result().findings,
    )


def decode_state(raw: bytes, schema_raw: bytes) -> DecodedState:
    parsed = parse_state_bytes(raw)
    if parsed.value is None:
        return DecodedState(None, parsed.findings)
    return decode_parsed_state(raw, parsed.value, schema_raw)
