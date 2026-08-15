from __future__ import annotations

import hashlib
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.local_execution.model import ProcessResult
from tools.local_execution.process import ProcessSpec, run_process
from tools.quality.check_repo_policy import REQUIRED
from tools.quality.tests.quality_hardening.assertions import check_process

REPO_ROOT = Path(__file__).resolve().parents[4]
POLICY_SOURCE = REPO_ROOT / "tools/quality/check_repo_policy.py"


@dataclass(frozen=True, slots=True, order=True)
class FileIdentity:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    files: tuple[FileIdentity, ...]


@dataclass(frozen=True, slots=True)
class QualityWorkspace:
    root: Path


@dataclass(frozen=True, slots=True)
class RepositoryPolicyFixture:
    root: Path

    @classmethod
    def create(
        cls,
        root: Path,
        *,
        with_git: bool = True,
    ) -> RepositoryPolicyFixture:
        fixture = cls(root)
        fixture._write_required_files()
        if with_git:
            fixture.require_git("init", "-q")
            fixture.require_git("add", ".")
        return fixture

    def _write_required_files(self) -> None:
        for relative in REQUIRED:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative == ".gitlint":
                shutil.copy2(REPO_ROOT / relative, path)
            else:
                path.write_text(f"fixture: {relative}\n", encoding="utf-8")
        checker = self.root / "tools/quality/check_repo_policy.py"
        checker.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(POLICY_SOURCE, checker)
        self.write(".gitignore", ".env\n.env.*\n!.env.example\n")

    def write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_bytes(self, relative: str, content: bytes) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def remove(self, relative: str) -> None:
        (self.root / relative).unlink()

    def git(self, *arguments: str) -> ProcessResult:
        return run_process(
            ProcessSpec("fixture-git", ("git", *arguments)),
            self.root,
        )

    def require_git(self, *arguments: str) -> None:
        result = self.git(*arguments)
        check_process(result, 0, f"git {' '.join(arguments)}")

    def policy(
        self,
        *arguments: str,
        pr_title: str | None = None,
    ) -> ProcessResult:
        environment = () if pr_title is None else (("PR_TITLE", pr_title),)
        return run_process(
            ProcessSpec(
                "repository-policy-fixture",
                (
                    sys.executable,
                    "tools/quality/check_repo_policy.py",
                    *arguments,
                ),
                environment,
            ),
            self.root,
        )

    def snapshot(self) -> SourceSnapshot:
        identities = (
            FileIdentity(
                path.relative_to(self.root).as_posix(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_size,
            )
            for path in self.root.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(self.root).parts
        )
        return SourceSnapshot(tuple(sorted(identities)))


def callable_source(
    declaration: str,
    physical_lines: int,
    *,
    decorator: bool = False,
) -> str:
    prefix = ["@marker"] if decorator else []
    body_lines = physical_lines - len(prefix) - 1
    return "\n".join([*prefix, declaration, *["    pass"] * body_lines]) + "\n"


def run_ruff(path: Path) -> ProcessResult:
    return run_process(
        ProcessSpec(
            "ruff-line-fixture",
            (
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--config",
                str(REPO_ROOT / "tools/quality/ruff-lint.toml"),
                str(path),
            ),
        ),
        REPO_ROOT,
    )


def run_gitlint(tmp_path: Path, message: str) -> ProcessResult:
    message_file = tmp_path / "COMMIT_EDITMSG"
    message_file.write_text(message, encoding="utf-8")
    return run_process(
        ProcessSpec(
            "gitlint-message-fixture",
            (
                sys.executable,
                "-m",
                "gitlint.cli",
                "--config",
                str(REPO_ROOT / ".gitlint"),
                "--msg-filename",
                str(message_file),
            ),
        ),
        REPO_ROOT,
    )
