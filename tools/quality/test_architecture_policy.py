from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from tools.quality.repository_paths import (
    GitPathMode,
    RepositoryPathError,
    regular_repository_file,
    repository_paths,
)
from tools.quality.source_policy import suppression_lines

ROOT = Path(__file__).resolve().parents[2]
QUALITY_ROOT = Path("tools/quality/tests/quality_hardening")
_TEST_SOURCE_SUFFIXES = frozenset({".py", ".pyi"})
_ALLURE_ROOTS = frozenset({"allure", "allure_commons"})
_TYPING_ROOTS = frozenset({"typing", "typing_extensions"})
_CAST_BINDINGS = frozenset({"typing.cast", "typing_extensions.cast"})
_PROPAGATED_TYPING_BINDINGS = _TYPING_ROOTS | _CAST_BINDINGS


class TestRule(StrEnum):
    PARSE = "TA001"
    RAW_ASSERT = "TA002"
    UNITTEST = "TA003"
    DIRECT_ALLURE = "TA004"
    TYPE_CAST = "TA005"
    SUPPRESSION = "TA006"
    FILE_BOUNDARY = "TA007"


@dataclass(frozen=True, slots=True, order=True)
class TestArchitectureViolation:
    path: str
    line: int
    rule: TestRule
    detail: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.rule.value} {self.detail}"


def _root_module(qualified_name: str) -> str:
    return qualified_name.split(".", 1)[0]


class _CastImportVisitor(ast.NodeVisitor):
    """Track only direct names and straight-line aliases.

    Dynamic lookup, importlib resolution and general path-sensitive flow are outside
    this advisory rule. Conditional and loop bodies are scanned from a copy of the
    incoming bindings, so a possible branch-local clear never proves an outer alias
    safe.
    """

    def __init__(self, path: Path) -> None:
        self._rendered = path.as_posix()
        self._scopes: list[dict[str, str | None]] = [{}]
        self.violations: list[TestArchitectureViolation] = []

    def _bind(self, name: str, qualified: str | None) -> None:
        self._scopes[-1][name] = qualified

    def _resolve(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            for scope in reversed(self._scopes):
                if node.id in scope:
                    return scope[node.id]
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = self._resolve(node.value)
            return f"{prefix}.{node.attr}" if prefix else None
        return None

    def _assignment_binding(self, value: ast.expr) -> str | None:
        qualified = self._resolve(value)
        if qualified in _PROPAGATED_TYPING_BINDINGS:
            return qualified
        return None

    def _violation(self, line: int) -> None:
        self.violations.append(
            TestArchitectureViolation(
                self._rendered,
                line,
                TestRule.TYPE_CAST,
                "typing.cast and typing_extensions.cast are forbidden",
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._bind(alias.asname or alias.name.split(".", 1)[0], alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if _root_module(module) in _TYPING_ROOTS and any(
            alias.name in {"cast", "*"} for alias in node.names
        ):
            self._violation(node.lineno)
        for alias in node.names:
            self._bind(alias.asname or alias.name, f"{module}.{alias.name}")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._resolve(node) in _CAST_BINDINGS:
            self._violation(node.lineno)
        self.generic_visit(node)

    def _shadow_target(self, target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            self._bind(target.id, None)
        elif isinstance(target, (ast.List, ast.Tuple)):
            for element in target.elts:
                self._shadow_target(element)
        elif isinstance(target, ast.Starred):
            self._shadow_target(target.value)

    def _bind_assignment_target(
        self,
        target: ast.expr,
        qualified: str | None,
    ) -> None:
        if isinstance(target, ast.Name):
            self._bind(target.id, qualified)
        else:
            self._shadow_target(target)

    def _visit_isolated(
        self,
        statements: list[ast.stmt],
        shadow: ast.expr | None = None,
    ) -> None:
        previous = self._scopes[-1].copy()
        if shadow is not None:
            self._shadow_target(shadow)
        for statement in statements:
            self.visit(statement)
        self._scopes[-1] = previous

    def visit_Assign(self, node: ast.Assign) -> None:
        qualified = self._assignment_binding(node.value)
        self.visit(node.value)
        for target in node.targets:
            self.visit(target)
            self._bind_assignment_target(target, qualified)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        qualified = (
            self._assignment_binding(node.value) if node.value is not None else None
        )
        self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        self.visit(node.target)
        self._bind_assignment_target(node.target, qualified)

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        self._visit_isolated(node.body)
        self._visit_isolated(node.orelse)

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        self._visit_isolated(node.body)
        self._visit_isolated(node.orelse)

    def _visit_loop(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        self._visit_isolated(node.body, node.target)
        self._visit_isolated(node.orelse)

    def visit_For(self, node: ast.For) -> None:
        self._visit_loop(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_loop(node)

    def _bind_arguments(self, arguments: ast.arguments) -> None:
        positional = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
        for argument in positional:
            self._bind(argument.arg, None)
        if arguments.vararg is not None:
            self._bind(arguments.vararg.arg, None)
        if arguments.kwarg is not None:
            self._bind(arguments.kwarg.arg, None)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        if node.returns is not None:
            self.visit(node.returns)
        self._bind(node.name, None)
        self._scopes.append({})
        self._bind_arguments(node.args)
        for statement in node.body:
            self.visit(statement)
        self._scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        self._scopes.append({})
        self._bind_arguments(node.args)
        self.visit(node.body)
        self._scopes.pop()


def _type_cast_violations(
    tree: ast.Module,
    path: Path,
) -> list[TestArchitectureViolation]:
    visitor = _CastImportVisitor(path)
    visitor.visit(tree)
    return visitor.violations


def _strict_quality_path(path: Path) -> bool:
    return path == QUALITY_ROOT or path.is_relative_to(QUALITY_ROOT)


def _imported_modules(node: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    return ((node.module or ""),)


def _global_violations(
    tree: ast.Module,
    path: Path,
) -> list[TestArchitectureViolation]:
    rendered = path.as_posix()
    violations: list[TestArchitectureViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and path.name != "assertions.py":
            violations.append(
                TestArchitectureViolation(
                    rendered,
                    node.lineno,
                    TestRule.RAW_ASSERT,
                    "raw assert is allowed only in a test assertions.py boundary",
                )
            )
    return violations


def _strict_violations(
    tree: ast.Module,
    source: str,
    path: Path,
) -> list[TestArchitectureViolation]:
    rendered = path.as_posix()
    violations: list[TestArchitectureViolation] = []
    reporting_adapter = path.name == "reporting.py"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = _imported_modules(node)
            roots = frozenset(_root_module(module) for module in modules)
            if "unittest" in roots:
                violations.append(
                    TestArchitectureViolation(
                        rendered,
                        node.lineno,
                        TestRule.UNITTEST,
                        "unittest and unittest.mock are forbidden",
                    )
                )
            if roots & _ALLURE_ROOTS and not reporting_adapter:
                violations.append(
                    TestArchitectureViolation(
                        rendered,
                        node.lineno,
                        TestRule.DIRECT_ALLURE,
                        "Allure access must stay behind a reporting.py boundary",
                    )
                )
    violations.extend(_type_cast_violations(tree, path))
    violations.extend(
        TestArchitectureViolation(
            rendered,
            line,
            TestRule.SUPPRESSION,
            "suppression comment is forbidden in the strict test surface",
        )
        for line in suppression_lines(source)
    )
    return violations


def scan_test_source(
    source: str,
    path: str,
) -> tuple[TestArchitectureViolation, ...]:
    relative = Path(path)
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        return (
            TestArchitectureViolation(
                path,
                error.lineno or 1,
                TestRule.PARSE,
                f"test source does not parse: {error.msg}",
            ),
        )
    violations = _global_violations(tree, relative)
    if _strict_quality_path(relative):
        violations.extend(
            _strict_violations(
                tree,
                source,
                relative,
            )
        )
    return tuple(sorted(set(violations)))


def _is_test_source(path: Path) -> bool:
    return path.suffix in _TEST_SOURCE_SUFFIXES and "tests" in path.parts


def scan_repository(root: Path = ROOT) -> tuple[TestArchitectureViolation, ...]:
    try:
        paths = repository_paths(
            root,
            GitPathMode.TRACKED_AND_UNTRACKED,
            exclude_directories=True,
        )
    except RepositoryPathError as error:
        return (
            TestArchitectureViolation(
                ".",
                1,
                TestRule.FILE_BOUNDARY,
                f"cannot discover test source: {error}",
            ),
        )
    violations: list[TestArchitectureViolation] = []
    for relative in paths:
        if not _is_test_source(relative):
            continue
        try:
            source_path = regular_repository_file(root, relative, missing_ok=True)
            if source_path is None:
                continue
            source = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, RepositoryPathError) as error:
            violations.append(
                TestArchitectureViolation(
                    relative.as_posix(),
                    1,
                    TestRule.FILE_BOUNDARY,
                    f"cannot read regular test source: {error}",
                )
            )
            continue
        violations.extend(scan_test_source(source, relative.as_posix()))
    return tuple(sorted(set(violations)))


def main() -> int:
    violations = scan_repository(Path.cwd())
    if violations:
        print("TEST ARCHITECTURE POLICY: FAIL")
        for violation in violations:
            print(f"- {violation.render()}")
        return 1
    print("TEST ARCHITECTURE POLICY: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
