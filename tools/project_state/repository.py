import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tools.project_state.git import run_git


class TreeReader(Protocol):
    def read(self, path: str) -> bytes | None: ...

    def mode(self, path: str) -> str | None: ...

    def commit_exists(self, commit: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class ResolvedCommit:
    oid: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{40}", self.oid) is None:
            raise ValueError("resolved commit must be a full lowercase Git OID")


def resolve_commit(repo: Path, revision: str) -> ResolvedCommit | None:
    result = run_git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if result.returncode != 0:
        return None
    try:
        return ResolvedCommit(result.stdout.decode("ascii").strip())
    except UnicodeDecodeError, ValueError:
        return None


@dataclass(frozen=True, slots=True)
class GitTree:
    repo: Path
    commit: ResolvedCommit

    @classmethod
    def resolve(cls, repo: Path, revision: str) -> GitTree | None:
        commit = resolve_commit(repo, revision)
        return None if commit is None else cls(repo, commit)

    def read(self, path: str) -> bytes | None:
        result = run_git(self.repo, "show", f"{self.commit.oid}:{path}")
        return result.stdout if result.returncode == 0 else None

    def mode(self, path: str) -> str | None:
        result = run_git(self.repo, "ls-tree", "-z", self.commit.oid, "--", path)
        if result.returncode != 0 or not result.stdout:
            return None
        header, _, actual = result.stdout.partition(b"\t")
        if actual.rstrip(b"\0").decode("utf-8", "strict") != path:
            return None
        return header.split(b" ", 1)[0].decode("ascii")

    def commit_exists(self, commit: str) -> bool:
        result = run_git(self.repo, "cat-file", "-t", commit)
        return result.returncode == 0 and result.stdout == b"commit\n"
