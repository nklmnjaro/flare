import json
from typing import Never

from tools.project_state.model import JSONValue


class StrictJSONError(ValueError):
    pass


class DuplicateKeyError(StrictJSONError):
    pass


def canonical_json_bytes(value: JSONValue) -> bytes:
    text = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return f"{text}\n".encode()


def _strict_object(pairs: list[tuple[str, JSONValue]]) -> dict[str, JSONValue]:
    result: dict[str, JSONValue] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(key)
        result[key] = value
    return result


def _reject_float(value: str) -> Never:
    raise StrictJSONError(f"floating-point number is forbidden: {value}")


def _reject_constant(value: str) -> Never:
    raise StrictJSONError(f"non-JSON number is forbidden: {value}")


def parse_strict_json(raw: bytes) -> JSONValue:
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise StrictJSONError(str(error)) from error
    try:
        decoded: JSONValue = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except DuplicateKeyError:
        raise
    except (json.JSONDecodeError, StrictJSONError) as error:
        raise StrictJSONError(str(error)) from error
    return decoded
