from __future__ import annotations

import unicodedata
from pathlib import PurePosixPath


class CanonicalPathError(ValueError):
    pass


def canonical_relative_posix_path(value: str, *, label: str) -> str:
    if not value:
        raise CanonicalPathError(f"{label} is empty")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as error:
        raise CanonicalPathError(f"{label} is not representable as UTF-8") from error
    if unicodedata.normalize("NFC", value) != value:
        raise CanonicalPathError(f"{label} is not NFC-normalized")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise CanonicalPathError(f"{label} contains a forbidden Unicode character")
    if "\\" in value:
        raise CanonicalPathError(f"{label} contains a backslash")
    if PurePosixPath(value).is_absolute():
        raise CanonicalPathError(f"{label} must be relative")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise CanonicalPathError(f"{label} is not canonical")
    if PurePosixPath(*parts).as_posix() != value:
        raise CanonicalPathError(f"{label} is not canonical")
    return value
