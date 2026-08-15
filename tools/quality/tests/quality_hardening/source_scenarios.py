import os
import stat

from tools.quality.repository_paths import (
    GitPathMode,
    RepositoryPathError,
    repository_paths,
    validate_repository_path,
)
from tools.quality.source_policy import (
    load_policy,
    scan_mypy_configuration,
    scan_non_python_lines,
    scan_python_source,
    scan_repository,
    suppression_lines,
)
from tools.quality.tests.quality_hardening.assertions import (
    check_contains,
    check_equal,
    check_process,
)
from tools.quality.tests.quality_hardening.reporting import reported, step
from tools.quality.tests.quality_hardening.scenario_catalog import (
    QH_N01,
    QH_N02,
    QH_N03,
    QH_N04,
    QH_N17,
    QH_N18,
)
from tools.quality.tests.quality_hardening.source_policy_support import (
    create_source_policy_fixture,
    run_mypy_source,
)
from tools.quality.tests.quality_hardening.support import (
    REPO_ROOT,
    QualityWorkspace,
    callable_source,
    run_ruff,
)

POLICY = load_policy(REPO_ROOT)

_RUFF_SUPPRESSIONS = (
    ("inline noqa", "def operation():\n    unused = 1  # noqa\n"),
    ("inline coded noqa", "def operation():\n    unused = 1  # noqa: F841\n"),
    (
        "inline coded noqa trailing comma",
        "def operation():\n    unused = 1  # noqa: F841,\n",
    ),
    (
        "inline coded noqa repeated comma",
        "def operation():\n    unused = 1  # noqa: F841,,\n",
    ),
    (
        "inline coded noqa leading comma",
        "def operation():\n    unused = 1  # noqa: ,F841\n",
    ),
    ("file Ruff noqa", "# ruff: noqa\ndef operation():\n    unused = 1\n"),
    ("file coded Ruff noqa", "# ruff: noqa: F841\ndef operation():\n    unused = 1\n"),
    ("file Flake8 noqa", "# flake8: noqa\ndef operation():\n    unused = 1\n"),
    (
        "file coded Flake8 noqa",
        "# flake8: noqa: F841\ndef operation():\n    unused = 1\n",
    ),
)
_MYPY_SUPPRESSIONS = (
    ("inline type ignore", "def operation() -> str:\n    return 1  # type: ignore\n"),
    (
        "inline coded type ignore",
        "def operation() -> str:\n    return 1  # type: ignore[return-value]\n",
    ),
    (
        "inline coded type ignore trailing comma",
        "def operation() -> str:\n    return 1  # type: ignore[return-value,]\n",
    ),
    (
        "inline empty coded type ignore",
        "def operation() -> str:\n    return 1  # type: ignore[]\n",
    ),
    (
        "inline delimiter-only type ignore",
        "def operation() -> str:\n    return 1  # type: ignore[,]\n",
    ),
    (
        "file ignore-errors",
        "# mypy: ignore-errors\ndef operation() -> str:\n    return 1\n",
    ),
    (
        "file ignore_errors truthy",
        "# mypy: ignore_errors = True\ndef operation() -> str:\n    return 1\n",
    ),
    (
        "file ignore_errors quoted truthy",
        '# mypy: ignore_errors = "true"\ndef operation() -> str:\n    return 1\n',
    ),
    (
        "file composed ignore_errors quoted truthy",
        (
            '# mypy: strict, ignore_errors = "true"\ndef operation() -> str:\n    return 1\n'
        ),
    ),
    (
        "file disable-error-code",
        (
            "# mypy: disable-error-code=return-value\ndef operation() -> str:\n    return 1\n"
        ),
    ),
    (
        "file disable_error_code",
        (
            '# mypy: disable_error_code = "return-value"\ndef operation() -> str:\n    return 1\n'
        ),
    ),
    (
        "file disable_error_code trailing comma",
        (
            '# mypy: disable_error_code = "return-value,"\ndef operation() -> str:\n    return 1\n'
        ),
    ),
)


@reported(QH_N01)
def verify_callable_green_variants() -> None:
    variants = (
        callable_source("def function():", POLICY.max_callable_lines),
        callable_source("async def operation():", POLICY.max_callable_lines),
        "class Owner:\n"
        + "\n".join(
            f"    {line}"
            for line in callable_source(
                "def method(self):",
                POLICY.max_callable_lines,
            ).splitlines()
        )
        + "\n",
        callable_source(
            "def decorated():",
            POLICY.max_callable_lines,
            decorator=True,
        ),
        "def outer():\n    def nested():\n        return 1\n    return nested()\n",
    )
    for index, source in enumerate(variants, 1):
        with step(f"Проверить допустимый вариант callable №{index}"):
            violations = scan_python_source(
                source,
                "fixture.py",
                POLICY.max_callable_lines,
            )
            check_equal(violations, [], f"variant {index} violations")


@reported(QH_N02)
def verify_callable_red() -> None:
    with step("Проверить callable длиной 81 строку"):
        source = callable_source("def oversized():", POLICY.max_callable_lines + 1)
        violations = scan_python_source(
            source,
            "fixture.py",
            POLICY.max_callable_lines,
        )
        check_equal(len(violations), 1, "oversized violation count")
        check_contains(
            f"has {POLICY.max_callable_lines + 1} physical lines",
            violations[0].detail,
            "oversized diagnostic",
        )


@reported(QH_N03)
def verify_decorator_and_nested_counting() -> None:
    with step("Включить decorator в физическую длину"):
        decorated = callable_source(
            "def decorated():",
            POLICY.max_callable_lines + 1,
            decorator=True,
        )
        decorated_violations = scan_python_source(
            decorated,
            "fixture.py",
            POLICY.max_callable_lines,
        )
        check_equal(len(decorated_violations), 1, "decorated violation count")
        check_equal(decorated_violations[0].line, 1, "decorated start line")
    with step("Проверить outer и nested callable независимо"):
        nested = callable_source("def nested():", POLICY.max_callable_lines + 1)
        source = "def outer():\n" + "\n".join(
            f"    {line}" for line in nested.splitlines()
        )
        violations = scan_python_source(source, "fixture.py", POLICY.max_callable_lines)
        details = "\n".join(item.detail for item in violations)
        check_contains("'outer'", details, "outer callable violation")
        check_contains("'outer.nested'", details, "nested callable violation")


@reported(QH_N04)
def verify_source_line_boundaries(workspace: QualityWorkspace) -> None:
    with step("Проверить non-Python строку 120/121"):
        green = scan_non_python_lines(
            "x" * POLICY.max_source_line,
            "fixture.sh",
            POLICY.max_source_line,
        )
        red = scan_non_python_lines(
            "x" * (POLICY.max_source_line + 1),
            "fixture.sh",
            POLICY.max_source_line,
        )
        check_equal(green, [], "120-character violations")
        check_equal(len(red), 1, "121-character violation count")
    with step("Проверить Python E501 на 120/121"):
        prefix, suffix = 'value = "', '"'
        payload = POLICY.max_source_line - len(prefix) - len(suffix)
        good = workspace.root / "good.py"
        bad = workspace.root / "bad.py"
        bypass = workspace.root / "bypass.py"
        good.write_text(f"{prefix}{'x' * payload}{suffix}\n", encoding="utf-8")
        bad.write_text(f"{prefix}{'x' * (payload + 1)}{suffix}\n", encoding="utf-8")
        bypass.write_text(
            f"{prefix}{'x' * (payload + 1)}{suffix}  # noqa: E501\n",
            encoding="utf-8",
        )
        accepted, rejected = run_ruff(good), run_ruff(bad)
        check_equal(accepted.returncode, 0, "Ruff 120-character exit")
        check_equal(rejected.returncode, 1, "Ruff 121-character exit")
        check_contains("E501", rejected.stdout, "Ruff 121-character diagnostic")
    with step("Отклонить попытку скрыть E501 через noqa"):
        bypassed = run_ruff(bypass)
        violations = scan_python_source(
            bypass.read_text(encoding="utf-8"),
            bypass.name,
            POLICY.max_callable_lines,
        )
        check_equal(bypassed.returncode, 0, "Ruff noqa bypass exit")
        check_equal(len(violations), 1, "source policy suppression count")
        check_contains(
            "suppression comment",
            violations[0].detail,
            "source policy suppression diagnostic",
        )
    with step("Сохранить Ruff modernization signal UP015"):
        outdated = workspace.root / "outdated.py"
        outdated.write_text(
            "from pathlib import Path\n\n"
            "def read(path: Path) -> str:\n"
            '    with open(path, "r") as stream:\n'
            "        return stream.read()\n",
            encoding="utf-8",
        )
        modernization = run_ruff(outdated)
        check_process(modernization, 1, "Ruff outdated idiom")
        check_contains("UP015", modernization.stdout, "Ruff UP015 diagnostic")


def _verify_git_and_no_git_symlink_boundaries(
    workspace: QualityWorkspace,
) -> None:
    outside = workspace.root / "outside-repository.py"
    outside.write_text("EXTERNAL_SOURCE = True\n", encoding="utf-8")
    for label, with_git in (("git", True), ("no-git", False)):
        fixture = create_source_policy_fixture(
            workspace.root / f"symlink-{label}",
            with_git=with_git,
        )
        leak = fixture.root / "leak.py"
        leak.symlink_to(outside)
        if with_git:
            fixture.require_git("add", "leak.py")
        violations = scan_repository(fixture.root)
        check_equal(len(violations), 1, f"число нарушений symlink {label}")
        check_equal(violations[0].path, "leak.py", f"путь symlink {label}")
        check_contains("symlink", violations[0].detail, f"диагностика {label}")


def _verify_source_classification(workspace: QualityWorkspace) -> None:
    for label, with_git in (("git", True), ("no-git", False)):
        fixture = create_source_policy_fixture(
            workspace.root / f"classification-{label}",
            with_git=with_git,
        )
        fixture.write_bytes("assets/logo.png", b"\x89PNG\r\n\x1a\n\xff")
        fixture.write_bytes("assets/archive.zip", b"PK\x03\x04\xff")
        fixture.write("regular.py", "VALUE = 1\n")
        fixture.write("regular.pyi", "VALUE: int\n")
        fixture.write("nested/example.editorconfig", "x" * 121 + "\n")
        fixture.write(".venv/ignored.py", "def broken(\n")
        check_equal(scan_repository(fixture.root), [], f"classification {label}")
    exact = create_source_policy_fixture(
        workspace.root / "exact-editorconfig",
        with_git=False,
    )
    exact.write(".editorconfig", "x" * 121 + "\n")
    violations = scan_repository(exact.root)
    check_equal(len(violations), 1, "число нарушений exact .editorconfig")
    check_equal(violations[0].path, ".editorconfig", "путь exact .editorconfig")
    stub = create_source_policy_fixture(workspace.root / "stub", with_git=False)
    stub.write("broken.pyi", "def broken(\n")
    violations = scan_repository(stub.root)
    check_equal(len(violations), 1, "число нарушений .pyi")
    check_contains("does not parse", violations[0].detail, "диагностика .pyi")


def _verify_discovery_fail_closed(workspace: QualityWorkspace) -> None:
    untracked = create_source_policy_fixture(workspace.root / "untracked")
    untracked.write("untracked.py", "def broken(\n")
    violations = scan_repository(untracked.root)
    check_equal(len(violations), 1, "число нарушений untracked source")
    check_equal(violations[0].path, "untracked.py", "путь untracked source")
    git_non_regular = create_source_policy_fixture(workspace.root / "git-non-regular")
    git_non_regular.write("special.py", "VALUE = 1\n")
    git_non_regular.require_git("add", "special.py")
    special = git_non_regular.root / "special.py"
    special.unlink()
    special.mkdir()
    violations = scan_repository(git_non_regular.root)
    check_equal(len(violations), 1, "число нарушений Git non-regular source")
    check_contains("not a regular file", violations[0].detail, "Git non-regular")
    non_regular = create_source_policy_fixture(
        workspace.root / "non-regular",
        with_git=False,
    )
    os.mkfifo(non_regular.root / "special.py")
    violations = scan_repository(non_regular.root)
    check_equal(len(violations), 1, "число нарушений non-regular source")
    check_contains("not a regular file", violations[0].detail, "non-regular source")
    malformed = create_source_policy_fixture(workspace.root / "malformed-index")
    malformed.write_bytes(".git/index", b"not-a-git-index")
    first = scan_repository(malformed.root)
    second = scan_repository(malformed.root)
    check_equal(first, second, "детерминированная ошибка Git index")
    check_equal(len(first), 1, "число ошибок Git index")
    check_contains("unable to read Git index", first[0].detail, "ошибка Git index")


def _verify_foreign_git_metadata_rejected(workspace: QualityWorkspace) -> None:
    external = create_source_policy_fixture(workspace.root / "external-git-root")
    external.write("external.py", "EXTERNAL = True\n")
    external.require_git("add", "external.py")
    fixture = create_source_policy_fixture(
        workspace.root / "foreign-git-metadata",
        with_git=False,
    )
    (fixture.root / ".git").symlink_to(external.root / ".git", target_is_directory=True)
    violations = scan_repository(fixture.root)
    check_equal(len(violations), 1, "число ошибок foreign Git metadata")
    check_contains("Git metadata is a symlink", violations[0].detail, "foreign Git")


def _verify_no_git_leaf_discovery(workspace: QualityWorkspace) -> None:
    fixture = create_source_policy_fixture(
        workspace.root / "leaf-discovery",
        with_git=False,
    )
    fixture.write("vendor/ignored.py", "VALUE = 1\n")
    fixture.write("package/regular.py", "VALUE = 1\n")
    (fixture.root / "looks-like-source.py").mkdir()
    outside = workspace.root / "outside-directory"
    outside.mkdir()
    (outside / "not-followed.py").write_text("VALUE = 1\n", encoding="utf-8")
    (fixture.root / "linked.py").symlink_to(outside, target_is_directory=True)
    os.mkfifo(fixture.root / "special.py")

    complete = repository_paths(fixture.root, GitPathMode.TRACKED)
    rendered = frozenset(path.as_posix() for path in complete)
    check_equal("vendor/ignored.py" in rendered, True, "unpruned vendor leaf")
    check_equal("linked.py" in rendered, True, "directory symlink leaf")
    check_equal(
        "linked.py/not-followed.py" in rendered,
        False,
        "directory symlink is not followed",
    )
    check_equal("special.py" in rendered, True, "non-regular leaf")
    check_equal(
        "looks-like-source.py" in rendered,
        False,
        "source-like regular directory",
    )
    check_equal(
        any(stat.S_ISDIR((fixture.root / path).lstat().st_mode) for path in complete),
        False,
        "regular directories are not repository leaves",
    )
    excluded = repository_paths(
        fixture.root,
        GitPathMode.TRACKED,
        exclude_directories=True,
    )
    check_equal(
        "vendor/ignored.py" in {path.as_posix() for path in excluded},
        False,
        "requested excluded-directory pruning",
    )


def _verify_unicode_discovery_boundaries(workspace: QualityWorkspace) -> None:
    ambiguous_name = "ambiguous-\u202e.py"
    for label, with_git in (("git", True), ("no-git", False)):
        fixture = create_source_policy_fixture(
            workspace.root / f"unicode-{label}",
            with_git=with_git,
        )
        fixture.write(ambiguous_name, "VALUE = 1\n")
        if with_git:
            fixture.require_git("add", ambiguous_name)
        violations = scan_repository(fixture.root)
        check_equal(len(violations), 1, f"число Unicode ошибок {label}")
        check_contains(
            (
                "Git returned an invalid repository path"
                if with_git
                else "forbidden Unicode character"
            ),
            violations[0].detail,
            f"Unicode path diagnostic {label}",
        )

    for label, with_git in (("git", True), ("no-git", False)):
        fixture = create_source_policy_fixture(
            workspace.root / f"invalid-utf8-{label}",
            with_git=with_git,
        )
        descriptor = os.open(
            os.fsencode(fixture.root) + b"/invalid-\xff.py",
            os.O_WRONLY | os.O_CREAT,
            0o644,
        )
        try:
            os.write(descriptor, b"VALUE = 1\n")
        finally:
            os.close(descriptor)
        if with_git:
            fixture.require_git("add", "-A")
        violations = scan_repository(fixture.root)
        check_equal(len(violations), 1, f"число invalid UTF-8 ошибок {label}")
        check_contains(
            (
                "Git returned an invalid repository path"
                if with_git
                else "not representable as UTF-8"
            ),
            violations[0].detail,
            f"invalid UTF-8 diagnostic {label}",
        )


def _verify_relative_path_validation() -> None:
    invalid = (
        "/absolute.py",
        "../escape.py",
        "a//b.py",
        "a/./b.py",
        "a\\b.py",
        "not-nfc-e\u0301.py",
        "control-\x7f.py",
        "format-\u202e.py",
        "surrogate-\udcff.py",
        "private-use-\ue000.py",
        "unassigned-\u0378.py",
    )
    rejected = 0
    for value in invalid:
        try:
            validate_repository_path(value)
        except RepositoryPathError:
            rejected += 1
    check_equal(rejected, len(invalid), "число отклонённых repository paths")
    check_equal(
        validate_repository_path("пример.py").as_posix(),
        "пример.py",
        "NFC Unicode repository path",
    )


@reported(QH_N17)
def verify_source_discovery_boundaries(workspace: QualityWorkspace) -> None:
    with step("Отклонить supported source symlink в Git и source-only tree"):
        _verify_git_and_no_git_symlink_boundaries(workspace)
    with step("Классифицировать source до decode и поддержать .pyi"):
        _verify_source_classification(workspace)
    with step("Закрыть Git failure, untracked и non-regular границы"):
        _verify_discovery_fail_closed(workspace)
        _verify_foreign_git_metadata_rejected(workspace)
    with step("Возвращать только no-Git leaves и pruning только по запросу"):
        _verify_no_git_leaf_discovery(workspace)
    with step("Отклонить ambiguous Unicode paths в Git и no-Git"):
        _verify_unicode_discovery_boundaries(workspace)
    with step("Отклонить неканонические repository-relative paths"):
        _verify_relative_path_validation()


def _verify_ruff_suppressions(workspace: QualityWorkspace) -> None:
    for index, (label, source) in enumerate(_RUFF_SUPPRESSIONS, 1):
        path = workspace.root / f"ruff-suppression-{index}.py"
        path.write_text(source, encoding="utf-8")
        tool_result = run_ruff(path)
        check_process(tool_result, 0, f"Ruff подавляет ошибку: {label}")
        violations = scan_python_source(
            source,
            path.name,
            POLICY.max_callable_lines,
        )
        check_equal(len(violations), 1, f"Flare отклоняет {label}")
        check_contains("suppression comment", violations[0].detail, label)


def _verify_mypy_suppressions() -> None:
    for label, source in _MYPY_SUPPRESSIONS:
        tool_result = run_mypy_source(source)
        check_process(tool_result, 0, f"mypy подавляет ошибку: {label}")
        violations = scan_python_source(
            source,
            "mypy-suppression.py",
            POLICY.max_callable_lines,
        )
        check_equal(len(violations), 1, f"Flare отклоняет {label}")
        check_contains("suppression comment", violations[0].detail, label)


def _verify_suppression_near_misses() -> None:
    source = (
        'DIRECTIVES = """# noqa\n# noqa: F841\n# ruff: noqa\n'
        "# ruff: noqa: F841\n# flake8: noqa\n# flake8: noqa: F841\n"
        "# type: ignore\n# type: ignore[return-value]\n"
        "# mypy: ignore-errors\n# mypy: ignore_errors = True\n"
        "# mypy: disable-error-code=return-value\n"
        '# mypy: disable_error_code = "return-value"\n"""\n'
        "# Документация упоминает # noqa и # mypy: ignore-errors\n"
        "# noqaish\n"
        "# noqa-not-a-directive\n"
        "# ruff: noqaish\n"
        "# type: ignored\n"
        "# type: ignore-other\n"
        "# mypy: ignore-errors-disabled\n"
        "# mypy: disable-error-code-disabled=return-value\n"
        "# mypy: ignore_errors = False\n"
    )
    check_equal(suppression_lines(source), (), "suppression text и near misses")
    check_equal(
        scan_python_source(source, "prose.py", POLICY.max_callable_lines),
        [],
        "source с suppression text и near misses",
    )


def _verify_mypy_configuration_suppressions(workspace: QualityWorkspace) -> None:
    red_cases = (
        ("global ignore", "[tool.mypy]\nignore_errors = true\n", "ignore_errors"),
        (
            "override ignore",
            "[[tool.mypy.overrides]]\nmodule = ['fixture']\nignore_errors = true\n",
            "ignore_errors",
        ),
        (
            "disabled codes",
            "[tool.mypy]\ndisable_error_code = ['return-value']\n",
            "disable_error_code",
        ),
        ("strict disabled", "[tool.mypy]\nstrict = false\n", "strict"),
        ("excluded source", "[tool.mypy]\nexclude = ['tools/']\n", "exclude"),
        ("skipped imports", "[tool.mypy]\nfollow_imports = 'skip'\n", "follow_imports"),
    )
    for label, source, key in red_cases:
        violations = scan_mypy_configuration(source, "pyproject.toml")
        check_equal(bool(violations), True, f"Flare отклоняет config: {label}")
        check_contains(key, "\n".join(item.detail for item in violations), label)
    green = (
        "[tool.mypy]\n"
        "explicit_package_bases = true\n"
        "mypy_path = 'typings'\n"
        "python_version = '3.14'\n"
        "strict = true\n"
    )
    check_equal(
        scan_mypy_configuration(green, "pyproject.toml"),
        [],
        "non-suppressing mypy config",
    )

    fixture = create_source_policy_fixture(workspace.root / "mypy-config-suppression")
    fixture.write(
        "pyproject.toml",
        "[tool.flare.quality]\nmax-callable-lines = 80\n[tool.mypy]\nignore_errors = true\n",
    )
    violations = scan_repository(fixture.root)
    check_equal(len(violations), 1, "repository config suppression count")
    check_contains(
        "ignore_errors", violations[0].detail, "repository config suppression"
    )


@reported(QH_N18)
def verify_pinned_tool_suppression_boundaries(
    workspace: QualityWorkspace,
) -> None:
    with step("Доказать и отклонить Ruff suppression forms"):
        _verify_ruff_suppressions(workspace)
    with step("Доказать и отклонить mypy suppression forms"):
        _verify_mypy_suppressions()
    with step("Отклонить mypy suppression в TOML configuration"):
        _verify_mypy_configuration_suppressions(workspace)
    with step("Принять строки, prose и near-miss комментарии"):
        _verify_suppression_near_misses()
