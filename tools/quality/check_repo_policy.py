# flare-bootstrap-managed: v1
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

sys.dont_write_bytecode = True

if TYPE_CHECKING or __package__:
    from tools.quality.repository_paths import (
        GitPathMode,
        RepositoryPathError,
        has_git_metadata,
        regular_repository_file,
        repository_paths,
    )
else:
    from repository_paths import (
        GitPathMode,
        RepositoryPathError,
        has_git_metadata,
        regular_repository_file,
        repository_paths,
    )

ROOT = Path(__file__).resolve().parents[2]

REQUIRED = (
    ".gitlint",
    ".pre-commit-config.yaml",
    "README.md",
    "Makefile",
    ".editorconfig",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
    ".github/workflows/repo-policy.yml",
    "docs/engineering/ENGINEERING_STANDARD.md",
    "docs/onboarding/START-HERE.md",
    "pyproject.toml",
    "tools/quality/ruff-lint.toml",
    "tools/quality/source_policy.py",
    "tools/quality/test_architecture_policy.py",
)

FORBIDDEN_NAMES = {
    ".env",
    "credentials.json",
    "id_rsa",
}


def _required_file_errors(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED:
        try:
            path = regular_repository_file(root, Path(relative), missing_ok=True)
        except RepositoryPathError as error:
            errors.append(f"invalid required repository file: {relative}: {error}")
            continue
        if path is None:
            errors.append(f"missing required repository file: {relative}")
    return errors


def _git_index_files(root: Path) -> tuple[list[Path] | None, list[str]]:
    """Return tracked repository paths, or None for a source tree without Git metadata."""
    try:
        if not has_git_metadata(root):
            return None, []
        return list(repository_paths(root, GitPathMode.TRACKED)), []
    except RepositoryPathError as error:
        return [], [str(error)]


def _repository_files(root: Path) -> tuple[list[Path], list[str]]:
    try:
        return list(
            repository_paths(
                root,
                GitPathMode.TRACKED,
                exclude_directories=not has_git_metadata(root),
            )
        ), []
    except RepositoryPathError as error:
        return [], [str(error)]


def _is_forbidden_repository_path(relative: Path) -> bool:
    name = relative.name
    if name == ".env.example":
        return False
    return (
        name in FORBIDDEN_NAMES
        or name.startswith((".env.", "credentials.", "secrets."))
        or name.endswith((".pem", ".key"))
    )


def _pr_title_errors(root: Path, env: Mapping[str, str]) -> list[str]:
    title = env.get("PR_TITLE", "")
    if not title.strip():
        return []
    try:
        config = regular_repository_file(root, Path(".gitlint"))
    except RepositoryPathError:
        return []
    if config is None:
        return []
    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "gitlint.cli",
            "--config",
            str(config),
        ),
        cwd=root,
        input=f"{title}\n",
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode == 0:
        return []
    detail = (result.stdout or result.stderr).strip()
    return [f"PR title violates the commit contract: {detail or 'gitlint failed'}"]


def check(
    root: Path = ROOT,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    errors = _required_file_errors(root)
    errors.extend(_pr_title_errors(root, os.environ if env is None else env))

    repository_files, repository_errors = _repository_files(root)
    errors.extend(repository_errors)
    for rel in repository_files:
        if _is_forbidden_repository_path(rel):
            errors.append(f"forbidden tracked/source file: {rel.as_posix()}")

    return errors


def doctor(root: Path = ROOT) -> int:
    errors = _required_file_errors(root)
    tracked, git_errors = _git_index_files(root)
    errors.extend(git_errors)

    print("repo_root=.")
    print(f"python={sys.version.split()[0]}")
    if tracked is None:
        print("git_index=NOT_APPLICABLE")
    elif git_errors:
        print("git_index=FAIL")
    else:
        print("git_index=PASS")

    if errors:
        print("doctor=FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("doctor=PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doctor", action="store_true")
    args = parser.parse_args()

    if args.doctor:
        return doctor()

    errors = check()
    if errors:
        print("REPO POLICY: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("REPO POLICY: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
