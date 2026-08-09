import hashlib
import tempfile
from collections.abc import Callable
from pathlib import Path

from tools.project_state.git import run_git
from tools.project_state.model import (
    CandidateDefect,
    Finding,
    PreparedCandidate,
    PublicationResult,
    PublicationStatus,
    ValidationStatus,
)
from tools.project_state.projection import render_projection
from tools.project_state.repository import GitTree, ResolvedCommit, resolve_commit
from tools.project_state.validation import (
    PROJECTION_PATH,
    STATE_PATH,
    prevalidate_state,
    validate_candidate,
)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git_output(
    repo: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> str:
    result = run_git(repo, *args, env=env)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip())
    return result.stdout.decode("ascii").strip()


def _build_candidate_commit(
    repo: Path,
    expected_parent_oid: str,
    candidate_state: bytes,
    projection: bytes,
) -> str:
    with tempfile.TemporaryDirectory(prefix="flare-state-index-") as directory:
        index = str(Path(directory) / "index")
        env = {"GIT_INDEX_FILE": index}
        _git_output(repo, "read-tree", expected_parent_oid, env=env)
        for path, content in (
            (STATE_PATH, candidate_state),
            (PROJECTION_PATH, projection),
        ):
            blob = run_git(repo, "hash-object", "-w", "--stdin", input_bytes=content)
            if blob.returncode != 0:
                raise RuntimeError(blob.stderr.decode("utf-8", "replace"))
            object_id = blob.stdout.decode("ascii").strip()
            _git_output(
                repo,
                "update-index",
                "--add",
                "--cacheinfo",
                f"100644,{object_id},{path}",
                env=env,
            )
        candidate_tree = _git_output(repo, "write-tree", env=env)
    commit_env = {
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_AUTHOR_EMAIL": "coordination-state@flare.invalid",
        "GIT_AUTHOR_NAME": "Flare Coordination State",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_COMMITTER_EMAIL": "coordination-state@flare.invalid",
        "GIT_COMMITTER_NAME": "Flare Coordination State",
    }
    commit = run_git(
        repo,
        "commit-tree",
        candidate_tree,
        "-p",
        expected_parent_oid,
        input_bytes=b"chore(project): publish coordination state\n",
        env=commit_env,
    )
    if commit.returncode != 0:
        raise RuntimeError(commit.stderr.decode("utf-8", "replace"))
    return commit.stdout.decode("ascii").strip()


def _prepare_candidate(
    repo: Path,
    expected_parent_oid: str,
    candidate_state: bytes,
) -> PreparedCandidate | CandidateDefect:
    candidate_sha = _sha256_bytes(candidate_state)
    validation = prevalidate_state(
        candidate_state,
        GitTree(repo, ResolvedCommit(expected_parent_oid)),
    )
    if validation.result.status is not ValidationStatus.PASS:
        return CandidateDefect(
            expected_parent_oid,
            candidate_sha,
            validation.result.findings,
        )
    if validation.state is None:
        raise RuntimeError("prevalidation passed without a decoded state")
    candidate_oid = _build_candidate_commit(
        repo,
        expected_parent_oid,
        candidate_state,
        render_projection(validation.state),
    )
    exact_validation = validate_candidate(
        GitTree(repo, ResolvedCommit(candidate_oid))
    ).result
    if exact_validation.status is not ValidationStatus.PASS:
        return CandidateDefect(
            expected_parent_oid,
            candidate_sha,
            exact_validation.findings,
        )
    return PreparedCandidate(expected_parent_oid, candidate_oid, candidate_sha)


def prepare_candidate(
    repo: Path,
    expected_parent: str,
    candidate_state: bytes,
) -> PreparedCandidate | CandidateDefect:
    resolved_parent = resolve_commit(repo, expected_parent)
    if resolved_parent is None:
        raise ValueError("expected_parent must resolve to a commit")
    return _prepare_candidate(repo, resolved_parent.oid, candidate_state)


def _publication_result(
    status: PublicationStatus,
    expected_parent_oid: str,
    expected_state_sha256: str,
    candidate_oid: str | None,
    candidate_state_sha256: str | None = None,
    findings: frozenset[Finding] = frozenset(),
) -> PublicationResult:
    return PublicationResult(
        status,
        expected_parent_oid,
        expected_state_sha256,
        candidate_oid,
        candidate_state_sha256,
        findings,
    )


def _publish_pinned_candidate(
    repo: Path,
    ref: str,
    expected_parent: ResolvedCommit,
    expected_state_sha256: str,
    candidate: ResolvedCommit,
    before_cas: Callable[[], None] | None,
) -> PublicationResult:
    invalid = _publication_result(
        PublicationStatus.INVALID_CANDIDATE,
        expected_parent.oid,
        expected_state_sha256,
        candidate.oid,
    )
    if not ref.startswith("refs/"):
        return invalid

    parent_line = _git_output(
        repo,
        "rev-list",
        "--parents",
        "-n",
        "1",
        candidate.oid,
    ).split()
    if len(parent_line) != 2 or parent_line[1] != expected_parent.oid:
        return invalid

    tree = GitTree(repo, candidate)
    validation = validate_candidate(tree).result
    state = tree.read(STATE_PATH)
    if state is None:
        return invalid
    candidate_sha = _sha256_bytes(state)
    if validation.status is not ValidationStatus.PASS:
        return _publication_result(
            PublicationStatus.STATE_DEFECT,
            expected_parent.oid,
            expected_state_sha256,
            candidate.oid,
            candidate_sha,
            validation.findings,
        )

    current = run_git(repo, "rev-parse", "--verify", ref)
    current_oid = (
        current.stdout.decode("ascii").strip() if current.returncode == 0 else ""
    )
    source_state = GitTree(repo, expected_parent).read(STATE_PATH)
    if (
        current_oid != expected_parent.oid
        or source_state is None
        or _sha256_bytes(source_state) != expected_state_sha256
    ):
        return _publication_result(
            PublicationStatus.STALE_PREIMAGE,
            expected_parent.oid,
            expected_state_sha256,
            candidate.oid,
            candidate_sha,
        )

    if before_cas is not None:
        before_cas()
    update = run_git(
        repo,
        "update-ref",
        ref,
        candidate.oid,
        expected_parent.oid,
    )
    if update.returncode == 0:
        status = PublicationStatus.PASS
    else:
        after = run_git(repo, "rev-parse", "--verify", ref)
        after_oid = (
            after.stdout.decode("ascii").strip() if after.returncode == 0 else ""
        )
        status = (
            PublicationStatus.STALE_PREIMAGE
            if after_oid != expected_parent.oid
            else PublicationStatus.INVALID_CANDIDATE
        )
    return _publication_result(
        status,
        expected_parent.oid,
        expected_state_sha256,
        candidate.oid,
        candidate_sha,
    )


def publish_candidate(
    repo: Path,
    ref: str,
    expected_parent: str,
    expected_state_sha256: str,
    candidate_commit: str,
    before_cas: Callable[[], None] | None = None,
) -> PublicationResult:
    resolved_parent = resolve_commit(repo, expected_parent)
    resolved_candidate = resolve_commit(repo, candidate_commit)
    if resolved_parent is None or resolved_candidate is None:
        return _publication_result(
            PublicationStatus.INVALID_CANDIDATE,
            resolved_parent.oid if resolved_parent is not None else "",
            expected_state_sha256,
            resolved_candidate.oid if resolved_candidate is not None else None,
        )
    return _publish_pinned_candidate(
        repo,
        ref,
        resolved_parent,
        expected_state_sha256,
        resolved_candidate,
        before_cas,
    )


def publish_state(
    repo: Path,
    ref: str,
    expected_parent: str,
    expected_state_sha256: str,
    candidate_state: bytes,
) -> PublicationResult:
    resolved_parent = resolve_commit(repo, expected_parent)
    if resolved_parent is None:
        return _publication_result(
            PublicationStatus.INVALID_CANDIDATE,
            resolved_parent.oid if resolved_parent is not None else "",
            expected_state_sha256,
            None,
        )
    prepared = _prepare_candidate(repo, resolved_parent.oid, candidate_state)
    if isinstance(prepared, CandidateDefect):
        return _publication_result(
            PublicationStatus.STATE_DEFECT,
            prepared.expected_coordination_parent_commit,
            expected_state_sha256,
            None,
            prepared.candidate_state_sha256,
            prepared.findings,
        )
    candidate = ResolvedCommit(prepared.candidate_coordination_commit)
    return _publish_pinned_candidate(
        repo,
        ref,
        resolved_parent,
        expected_state_sha256,
        candidate,
        None,
    )
