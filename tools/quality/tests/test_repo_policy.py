from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_SOURCE = REPO_ROOT / "tools/quality/check_repo_policy.py"
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


def _run(
    *command: str,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        command,
        cwd=cwd,
        env=process_env,
        check=False,
        capture_output=True,
        text=True,
    )


def _make_repo(tmp_path: Path, *, git: bool = True) -> Path:
    repo = tmp_path / "repo"
    for rel in REQUIRED:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture: {rel}\n", encoding="utf-8")

    checker = repo / "tools/quality/check_repo_policy.py"
    checker.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(POLICY_SOURCE, checker)
    (repo / ".gitignore").write_text(".env\n.env.*\n!.env.example\n", encoding="utf-8")

    if git:
        assert _run("git", "init", "-q", cwd=repo).returncode == 0
        assert _run("git", "add", ".", cwd=repo).returncode == 0
    return repo


def _policy(
    repo: Path,
    *args: str,
    pr_title: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {} if pr_title is None else {"PR_TITLE": pr_title}
    return _run(
        sys.executable,
        "tools/quality/check_repo_policy.py",
        *args,
        cwd=repo,
        env=env,
    )


def _source_snapshot(repo: Path) -> dict[str, bytes]:
    return {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(repo).parts
    }


def test_known_good_repository_is_green(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    result = _policy(repo, pr_title="test(quality): prove repository policy")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "REPO POLICY: PASS" in result.stdout


def test_missing_required_file_is_red_for_policy_and_doctor(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "docs/onboarding/START-HERE.md").unlink()

    policy = _policy(repo)
    doctor = _policy(repo, "--doctor")

    assert policy.returncode == 1
    assert (
        "missing required repository file: docs/onboarding/START-HERE.md"
        in policy.stdout
    )
    assert doctor.returncode == 1
    assert "doctor=FAIL" in doctor.stdout
    assert (
        "missing required repository file: docs/onboarding/START-HERE.md"
        in doctor.stdout
    )


def test_malformed_pr_title_is_red(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    result = _policy(repo, pr_title="quality please pass")

    assert result.returncode == 1
    assert "PR title must use Conventional Commits style" in result.stdout


def test_overlong_pr_title_is_red(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    title = "fix(quality): " + "x" * 60

    result = _policy(repo, pr_title=title)

    assert len(title) > 72
    assert result.returncode == 1
    assert "PR title must be <= 72 characters" in result.stdout


def test_ignored_local_env_is_green(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / ".env").write_text("LOCAL_ONLY=1\n", encoding="utf-8")

    result = _policy(repo)

    assert result.returncode == 0, result.stdout + result.stderr


def test_tracked_env_example_is_green(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / ".env.example").write_text("SAFE_PLACEHOLDER=change-me\n", encoding="utf-8")
    assert _run("git", "add", ".env.example", cwd=repo).returncode == 0

    result = _policy(repo)

    assert result.returncode == 0, result.stdout + result.stderr


def test_tracked_forbidden_env_is_red(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / ".env").write_text("SHOULD_NOT_BE_TRACKED=1\n", encoding="utf-8")
    assert _run("git", "add", "-f", ".env", cwd=repo).returncode == 0

    result = _policy(repo)

    assert result.returncode == 1
    assert "forbidden tracked/source file: .env" in result.stdout


def test_source_archive_forbidden_env_is_red(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, git=False)
    (repo / ".env").write_text("ARCHIVE_LEAK=1\n", encoding="utf-8")

    result = _policy(repo)

    assert result.returncode == 1
    assert "forbidden tracked/source file: .env" in result.stdout


def test_malformed_git_index_fails_deterministically(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / ".git/index").write_bytes(b"not-a-git-index")

    first = _policy(repo)
    second = _policy(repo)
    doctor = _policy(repo, "--doctor")

    assert first.returncode == second.returncode == 1
    assert first.stdout == second.stdout
    assert "unable to read Git index" in first.stdout
    assert doctor.returncode == 1
    assert "git_index=FAIL" in doctor.stdout
    assert "unable to read Git index" in doctor.stdout


def test_doctor_is_read_only_on_known_good_repo(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    before = _source_snapshot(repo)

    result = _policy(repo, "--doctor")

    after = _source_snapshot(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "doctor=PASS" in result.stdout
    assert before == after


def test_github_workflow_uses_canonical_make_command() -> None:
    workflow = (REPO_ROOT / ".github/workflows/repo-policy.yml").read_text(
        encoding="utf-8"
    )

    assert "run: make check-fast" in workflow
    assert "run: python3 tools/quality/check_repo_policy.py" not in workflow
