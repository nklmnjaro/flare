# flare-bootstrap-managed: v1
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REQUIRED = (
    "README.md",
    "Makefile",
    ".editorconfig",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
    ".github/workflows/repo-policy.yml",
    "docs/engineering/ENGINEERING_STANDARD.md",
    "docs/onboarding/START-HERE.md",
)

CONVENTIONAL_PR = re.compile(
    r"^(feat|fix|docs|style|refactor|test|chore|ci|build|perf|revert)"
    r"(\([a-z0-9-]+\))?: .+$"
)

FORBIDDEN_NAMES = {
    ".env",
    "credentials.json",
    "id_rsa",
}

WORKSPACE_DIRS = frozenset({".flare", ".git", ".venv", "node_modules"})


def _required_file_errors(root: Path) -> list[str]:
    return [
        f"missing required repository file: {rel}"
        for rel in REQUIRED
        if not (root / rel).is_file()
    ]


def _git_index_files(root: Path) -> tuple[list[Path] | None, list[str]]:
    """Return tracked repository paths, or None for a source tree without Git metadata."""
    if not (root / ".git").exists():
        return None, []

    git = shutil.which("git")
    if git is None:
        return [], ["Git is required to inspect tracked repository files"]

    result = subprocess.run(
        [git, "-C", str(root), "ls-files", "--cached", "-z"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        return [], ["unable to read Git index"]

    paths = [
        Path(os.fsdecode(raw_path))
        for raw_path in result.stdout.split(b"\0")
        if raw_path
    ]
    return paths, []


def _source_tree_files(root: Path) -> list[Path]:
    """Return source-like files when Git metadata is intentionally absent."""
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in WORKSPACE_DIRS for part in rel.parts):
            continue
        files.append(rel)
    return sorted(files, key=lambda item: item.as_posix())


def _repository_files(root: Path) -> tuple[list[Path], list[str]]:
    tracked, errors = _git_index_files(root)
    if errors:
        return [], errors
    if tracked is not None:
        return tracked, []
    return _source_tree_files(root), []


def _pr_title_errors(env: Mapping[str, str]) -> list[str]:
    title = env.get("PR_TITLE", "").strip()
    if not title:
        return []

    errors: list[str] = []
    if len(title) > 72:
        errors.append("PR title must be <= 72 characters")
    if not CONVENTIONAL_PR.fullmatch(title):
        errors.append(
            "PR title must use Conventional Commits style, e.g. "
            "'feat(ingest): accept event batch'"
        )
    return errors


def check(
    root: Path = ROOT,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    errors = _required_file_errors(root)
    errors.extend(_pr_title_errors(os.environ if env is None else env))

    repository_files, repository_errors = _repository_files(root)
    errors.extend(repository_errors)
    for rel in repository_files:
        if rel.name in FORBIDDEN_NAMES:
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
