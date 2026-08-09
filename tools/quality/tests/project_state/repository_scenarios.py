from dataclasses import dataclass

from tools.project_state.git import run_git
from tools.project_state.model import ValidationStatus
from tools.project_state.repository import GitTree
from tools.project_state.validation import (
    PROJECTION_PATH,
    SCHEMA_PATH,
    STATE_PATH,
    validate_candidate,
)
from tools.quality.tests.project_state.assertions import (
    assert_equal,
    assert_findings_equal,
)
from tools.quality.tests.project_state.reporting import attach_json, step_context
from tools.quality.tests.project_state.support import (
    RepositoryFixture,
    json_bytes,
    materialize_current_candidate,
)


@dataclass(slots=True)
class MovingRefTree:
    pinned: GitTree
    ref: str
    target: str
    moved: bool = False

    def read(self, path: str) -> bytes | None:
        content = self.pinned.read(path)
        if path == STATE_PATH and not self.moved:
            update = run_git(self.pinned.repo, "update-ref", self.ref, self.target)
            if update.returncode != 0:
                raise RuntimeError("cannot move adversarial validation ref")
            self.moved = True
        return content

    def mode(self, path: str) -> str | None:
        return self.pinned.mode(path)

    def commit_exists(self, commit: str) -> bool:
        return self.pinned.commit_exists(commit)


def verify_a1_c01_movable_ref_is_pinned(repository: RepositoryFixture) -> None:
    accepted_schema = repository.schema_bytes()
    accepted_projection = (repository.root / PROJECTION_PATH).read_bytes()
    repository.write(
        SCHEMA_PATH,
        json_bytes(
            {
                "$id": "urn:flare:coordination-state:1.0",
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "not": {},
            }
        ),
    )
    commit_a = repository.commit_paths("test: create invalid candidate A", SCHEMA_PATH)

    state_b = repository.copy_state()
    state_b["project_id"] = "not-flare"
    repository.write(SCHEMA_PATH, accepted_schema)
    repository.write(STATE_PATH, json_bytes(state_b))
    repository.write(PROJECTION_PATH, accepted_projection)
    commit_b = repository.commit_paths(
        "test: create invalid candidate B",
        SCHEMA_PATH,
        STATE_PATH,
        PROJECTION_PATH,
    )

    exact_a = validate_candidate(repository.tree(commit_a)).result
    exact_b = validate_candidate(repository.tree(commit_b)).result
    ref = "refs/heads/movable-validation"
    repository.git("update-ref", ref, commit_a)
    pinned = GitTree.resolve(repository.root, ref)
    if pinned is None:
        raise RuntimeError("movable validation ref did not resolve")
    moving = MovingRefTree(pinned, ref, commit_b)
    with step_context("Move candidate ref after its state bytes are read"):
        observed = validate_candidate(moving).result
        attach_json(
            "movable-ref attack result",
            {
                "commit_a": exact_a.as_dict(),
                "commit_b": exact_b.as_dict(),
                "pinned_result": observed.as_dict(),
            },
        )
    assert_equal(exact_a.status, ValidationStatus.STATE_DEFECT, "candidate A status")
    assert_equal(exact_b.status, ValidationStatus.STATE_DEFECT, "candidate B status")
    assert_equal(observed.as_dict(), exact_a.as_dict(), "single pinned-tree result")
    assert_equal(moving.moved, True, "adversarial ref movement occurred")


def verify_a1_c07_canonical_candidate_passes(repository: RepositoryFixture) -> None:
    observation = materialize_current_candidate(
        repository.root.parent / "canonical-candidate"
    )
    assert_findings_equal(observation, frozenset())
