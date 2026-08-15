import hashlib
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class _PinnedPublication:
    repo: Path
    ref: str
    expected_parent: ResolvedCommit
    expected_state_sha256: str
    candidate: ResolvedCommit
    before_cas: Callable[[], None] | None

    def result(
        self,
        status: PublicationStatus,
        candidate_state_sha256: str | None = None,
        findings: frozenset[Finding] = frozenset(),
    ) -> PublicationResult:
        return _publication_result(
            status,
            self.expected_parent.oid,
            self.expected_state_sha256,
            self.candidate.oid,
            candidate_state_sha256,
            findings,
        )


def _validated_candidate_state(
    publication: _PinnedPublication,
) -> str | PublicationResult:
    if not publication.ref.startswith("refs/"):
        return publication.result(PublicationStatus.INVALID_CANDIDATE)
    parent_line = _git_output(
        publication.repo,
        "rev-list",
        "--parents",
        "-n",
        "1",
        publication.candidate.oid,
    ).split()
    if len(parent_line) != 2 or parent_line[1] != publication.expected_parent.oid:
        return publication.result(PublicationStatus.INVALID_CANDIDATE)
    tree = GitTree(publication.repo, publication.candidate)
    validation = validate_candidate(tree).result
    state = tree.read(STATE_PATH)
    if state is None:
        return publication.result(PublicationStatus.INVALID_CANDIDATE)
    candidate_sha = _sha256_bytes(state)
    if validation.status is not ValidationStatus.PASS:
        return publication.result(
            PublicationStatus.STATE_DEFECT,
            candidate_sha,
            validation.findings,
        )
    return candidate_sha


def _preimage_is_current(publication: _PinnedPublication) -> bool:
    current = run_git(publication.repo, "rev-parse", "--verify", publication.ref)
    current_oid = (
        current.stdout.decode("ascii").strip() if current.returncode == 0 else ""
    )
    source_state = GitTree(publication.repo, publication.expected_parent).read(
        STATE_PATH
    )
    return (
        current_oid == publication.expected_parent.oid
        and source_state is not None
        and _sha256_bytes(source_state) == publication.expected_state_sha256
    )


def _update_ref_status(publication: _PinnedPublication) -> PublicationStatus:
    update = run_git(
        publication.repo,
        "update-ref",
        publication.ref,
        publication.candidate.oid,
        publication.expected_parent.oid,
    )
    if update.returncode == 0:
        return PublicationStatus.PASS
    after = run_git(publication.repo, "rev-parse", "--verify", publication.ref)
    after_oid = after.stdout.decode("ascii").strip() if after.returncode == 0 else ""
    if after_oid != publication.expected_parent.oid:
        return PublicationStatus.STALE_PREIMAGE
    return PublicationStatus.INVALID_CANDIDATE


def _publish_pinned_candidate(
    repo: Path,
    ref: str,
    expected_parent: ResolvedCommit,
    expected_state_sha256: str,
    candidate: ResolvedCommit,
    before_cas: Callable[[], None] | None,
) -> PublicationResult:
    publication = _PinnedPublication(
        repo,
        ref,
        expected_parent,
        expected_state_sha256,
        candidate,
        before_cas,
    )
    candidate_state = _validated_candidate_state(publication)
    if isinstance(candidate_state, PublicationResult):
        return candidate_state
    if not _preimage_is_current(publication):
        return publication.result(PublicationStatus.STALE_PREIMAGE, candidate_state)
    if publication.before_cas is not None:
        publication.before_cas()
    return publication.result(_update_ref_status(publication), candidate_state)


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
