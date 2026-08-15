from __future__ import annotations

import ast
import io
import re
import tokenize
import tomllib
from dataclasses import dataclass
from pathlib import Path

from tools.quality.repository_paths import (
    GitPathMode,
    RepositoryPathError,
    regular_repository_file,
    repository_paths,
)

ROOT = Path(__file__).resolve().parents[2]

_PYTHON_SOURCE_SUFFIXES = frozenset({".py", ".pyi"})
_TEXT_SOURCE_SUFFIXES = frozenset({".json", ".mjs", ".sh", ".toml", ".yaml", ".yml"})
_TEXT_SOURCE_NAMES = frozenset({".editorconfig", ".gitlint", "Makefile", "flare"})
_RUFF_SUPPRESSION = re.compile(
    r"^#\s*(?:(?:ruff|flake8)\s*:\s*)?(?i:noqa)(?=\s|:|$).*$"
)
_MYPY_INLINE_SUPPRESSION = re.compile(r"^#\s*type\s*:\s*ignore(?=\s|\[|$).*$")
_MYPY_IGNORE_ERRORS = re.compile(
    r"(?:^|,)\s*ignore[-_]errors"
    r'(?:\s*=\s*(?:"(?P<quoted>[A-Za-z0-9]+)"|'
    r"(?P<value>[A-Za-z0-9]+)))?(?=\s*(?:,|$))"
)
_MYPY_DISABLE_ERROR_CODE = re.compile(r"(?:^|,)\s*disable[-_]error[-_]code(?=\s*=)")
_MYPY_TRUE_VALUES = frozenset({"1", "on", "true", "yes"})
_CANONICAL_MYPY_OPTIONS: dict[str, object] = {
    "explicit_package_bases": True,
    "mypy_path": "typings",
    "python_version": "3.14",
    "strict": True,
}


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    max_callable_lines: int
    max_source_line: int


@dataclass(frozen=True, slots=True, order=True)
class SourceViolation:
    path: str
    line: int
    detail: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.detail}"


class _CallableVisitor(ast.NodeVisitor):
    def __init__(self, path: str, limit: int) -> None:
        self._path = path
        self._limit = limit
        self._scope: list[str] = []
        self.violations: list[SourceViolation] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_callable(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_callable(node)

    def _visit_callable(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        start = min([node.lineno, *(item.lineno for item in node.decorator_list)])
        end = node.end_lineno or node.lineno
        physical_lines = end - start + 1
        qualified_name = ".".join((*self._scope, node.name))
        if physical_lines > self._limit:
            self.violations.append(
                SourceViolation(
                    self._path,
                    start,
                    f"callable {qualified_name!r} has {physical_lines} physical "
                    f"lines (maximum {self._limit})",
                )
            )
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()


def _is_mypy_file_suppression(comment: str) -> bool:
    prefix = "# mypy:"
    normalized = comment.strip()
    if not normalized.startswith(prefix):
        return False
    options = normalized[len(prefix) :]
    ignore_match = _MYPY_IGNORE_ERRORS.search(options)
    if ignore_match is not None:
        value = ignore_match.group("quoted") or ignore_match.group("value")
        if value is None or value.lower() in _MYPY_TRUE_VALUES:
            return True
    return _MYPY_DISABLE_ERROR_CODE.search(options) is not None


def suppression_lines(source: str) -> tuple[int, ...]:
    return tuple(
        token.start[0]
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
        and (
            _RUFF_SUPPRESSION.fullmatch(token.string) is not None
            or _MYPY_INLINE_SUPPRESSION.fullmatch(token.string) is not None
            or _is_mypy_file_suppression(token.string)
        )
    )


def load_policy(root: Path) -> SourcePolicy:
    config = tomllib.loads(_read_policy_file(root, Path("pyproject.toml")))
    ruff_config = tomllib.loads(
        _read_policy_file(root, Path("tools/quality/ruff-lint.toml"))
    )
    tool = config.get("tool")
    if not isinstance(tool, dict):
        raise TypeError("pyproject.toml is missing [tool]")
    flare = tool.get("flare")
    if not isinstance(flare, dict):
        raise TypeError("pyproject.toml is missing Flare quality policy")
    quality = flare.get("quality")
    callable_limit = (
        quality.get("max-callable-lines") if isinstance(quality, dict) else None
    )
    line_limit = ruff_config.get("line-length")
    if not isinstance(callable_limit, int) or callable_limit < 1:
        raise ValueError("max-callable-lines must be a positive integer")
    if not isinstance(line_limit, int) or line_limit < 1:
        raise ValueError("Ruff lint line-length must be a positive integer")
    return SourcePolicy(callable_limit, line_limit)


def _read_policy_file(root: Path, relative: Path) -> str:
    path = regular_repository_file(root, relative)
    if path is None:
        raise RepositoryPathError(f"repository path is missing: {relative.as_posix()}")
    return path.read_text(encoding="utf-8")


def scan_python_source(
    source: str,
    path: str,
    limit: int,
) -> list[SourceViolation]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        return [
            SourceViolation(
                path,
                error.lineno or 1,
                f"Python source does not parse: {error.msg}",
            )
        ]
    visitor = _CallableVisitor(path, limit)
    visitor.visit(tree)
    visitor.violations.extend(
        SourceViolation(
            path,
            line,
            "suppression comment cannot bypass the source policy",
        )
        for line in suppression_lines(source)
    )
    return sorted(visitor.violations)


def scan_non_python_lines(
    source: str,
    path: str,
    limit: int,
) -> list[SourceViolation]:
    return [
        SourceViolation(
            path,
            number,
            f"source line has {len(line)} characters (maximum {limit})",
        )
        for number, line in enumerate(source.splitlines(), 1)
        if len(line) > limit
    ]


def _mypy_suppression_keys(value: object) -> frozenset[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "ignore_errors" and child is True:
                keys.add(key)
            if key == "disable_error_code" and bool(child):
                keys.add(key)
            keys.update(_mypy_suppression_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_mypy_suppression_keys(child))
    return frozenset(keys)


def _noncanonical_mypy_keys(mypy: dict[object, object]) -> frozenset[str]:
    keys = set(_mypy_suppression_keys(mypy))
    for raw_key, value in mypy.items():
        key = raw_key if isinstance(raw_key, str) else repr(raw_key)
        if key not in _CANONICAL_MYPY_OPTIONS or value != _CANONICAL_MYPY_OPTIONS[key]:
            keys.add(key)
    return frozenset(keys)


def scan_mypy_configuration(source: str, path: str) -> list[SourceViolation]:
    try:
        document = tomllib.loads(source)
    except tomllib.TOMLDecodeError:
        return []
    tool = document.get("tool")
    mypy = tool.get("mypy") if isinstance(tool, dict) else None
    if not isinstance(mypy, dict):
        return []
    violations: list[SourceViolation] = []
    for key in sorted(_noncanonical_mypy_keys(mypy)):
        match = re.search(rf"(?m)^\s*{re.escape(key)}\s*=", source)
        line = source.count("\n", 0, match.start()) + 1 if match is not None else 1
        violations.append(
            SourceViolation(
                path,
                line,
                f"mypy configuration option {key!r} is not canonical",
            )
        )
    return violations


def _is_python_source(path: Path) -> bool:
    return path.suffix in _PYTHON_SOURCE_SUFFIXES


def _is_text_source(path: Path) -> bool:
    return path.name in _TEXT_SOURCE_NAMES or path.suffix in _TEXT_SOURCE_SUFFIXES


def scan_repository(root: Path = ROOT) -> list[SourceViolation]:
    try:
        policy = load_policy(root)
    except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as error:
        return [SourceViolation("pyproject.toml", 1, f"invalid source policy: {error}")]
    try:
        paths = repository_paths(
            root,
            GitPathMode.TRACKED_AND_UNTRACKED,
            exclude_directories=True,
        )
    except RepositoryPathError as error:
        return [
            SourceViolation(
                ".",
                1,
                f"cannot enumerate repository source: {error}",
            )
        ]
    violations: list[SourceViolation] = []
    for relative in paths:
        python_source = _is_python_source(relative)
        text_source = _is_text_source(relative)
        if not python_source and not text_source:
            continue
        try:
            path = regular_repository_file(root, relative, missing_ok=True)
        except RepositoryPathError as error:
            violations.append(SourceViolation(relative.as_posix(), 1, str(error)))
            continue
        if path is None:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeError:
            violations.append(
                SourceViolation(relative.as_posix(), 1, "source is not valid UTF-8")
            )
            continue
        except OSError:
            violations.append(
                SourceViolation(relative.as_posix(), 1, "cannot read source")
            )
            continue
        if python_source:
            violations.extend(
                scan_python_source(
                    source,
                    relative.as_posix(),
                    policy.max_callable_lines,
                )
            )
        else:
            violations.extend(
                scan_non_python_lines(
                    source,
                    relative.as_posix(),
                    policy.max_source_line,
                )
            )
            if relative == Path("pyproject.toml"):
                violations.extend(scan_mypy_configuration(source, relative.as_posix()))
    return sorted(violations)


def main() -> int:
    violations = scan_repository(Path.cwd())
    if violations:
        print("SOURCE POLICY: FAIL")
        for violation in violations:
            print(f"- {violation.render()}")
        return 1
    print("SOURCE POLICY: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
