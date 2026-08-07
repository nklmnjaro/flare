from __future__ import annotations

import argparse
import os
import re
import sys
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
    r"(\([a-z0-9-]+\))?: .{1,}$"
)

FORBIDDEN_TRACKED = {
    ".env",
    "credentials.json",
    "id_rsa",
}


def check() -> list[str]:
    errors: list[str] = []

    for rel in REQUIRED:
        if not (ROOT / rel).exists():
            errors.append(f"missing required repository file: {rel}")

    title = os.environ.get("PR_TITLE", "").strip()
    if title and not CONVENTIONAL_PR.fullmatch(title):
        errors.append(
            "PR title must use Conventional Commits style, e.g. "
            "'feat(ingest): accept event batch'"
        )
    if len(title) > 72:
        errors.append("PR title must be <= 72 characters")

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", ".venv", "node_modules"} for part in path.parts):
            continue
        if path.name in FORBIDDEN_TRACKED:
            errors.append(f"forbidden tracked-looking file: {path.relative_to(ROOT)}")

    return errors


def doctor() -> int:
    print(f"repo_root={ROOT}")
    print(f"python={sys.version.split()[0]}")
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
