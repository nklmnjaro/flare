import hashlib

from tools.project_state.model import FindingCode, JSONValue
from tools.quality.tests.project_state.assertions import assert_findings_equal
from tools.quality.tests.project_state.support import (
    CHANGE_ID,
    RepositoryFixture,
    json_array,
    json_object,
)
from tools.quality.tests.project_state.validation_scenario_support import verify_finding


def _source(state: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return json_object(state.get("accepted_source_baseline"), "source baseline")


def _first_change(state: dict[str, JSONValue]) -> dict[str, JSONValue]:
    changes = json_array(state.get("active_changes"), "active changes")
    return json_object(changes[0], "first active change")


def verify_a1_n06_missing_source_commit(repository: RepositoryFixture) -> None:
    state = repository.copy_state()
    _source(state)["git_commit"] = "0" * 40
    verify_finding(
        repository.validate(state),
        FindingCode.UNRESOLVABLE_REFERENCE,
        "accepted_source_baseline",
        "git_commit",
    )


def verify_a1_n07_source_manifest_commit_mismatch(
    repository: RepositoryFixture,
) -> None:
    artifact = repository.add_artifact(
        "source-1",
        source_git_commit=repository.parent,
    )
    state = repository.copy_state()
    state["accepted_artifacts"] = [artifact]
    _source(state)["source_artifact_id"] = "source-1"
    verify_finding(
        repository.validate(state),
        FindingCode.CONTRADICTION,
        "accepted_source_baseline",
        "source_artifact_id",
    )


def verify_a1_n08_artifact_id_collision(repository: RepositoryFixture) -> None:
    first = repository.add_artifact("evidence-1", suffix="-a")
    second = repository.add_artifact("evidence-1", suffix="-b")
    state = repository.copy_state()
    state["accepted_artifacts"] = [first, second]
    verify_finding(
        repository.validate(state),
        FindingCode.INVALID_ARTIFACT,
        "accepted_artifacts",
        "evidence-1",
        "artifact_id",
    )


def verify_a1_n09_artifact_sha_mismatch(repository: RepositoryFixture) -> None:
    wrong_sha = hashlib.sha256(b"other\n").hexdigest()
    state = repository.copy_state()
    state["accepted_artifacts"] = [
        repository.add_artifact("evidence-1", state_sha=wrong_sha)
    ]
    verify_finding(
        repository.validate(state),
        FindingCode.SHA_MISMATCH,
        "accepted_artifacts",
        "evidence-1",
        "sha256",
    )


def verify_a1_n10_required_artifact_unresolved(
    repository: RepositoryFixture,
) -> None:
    state = repository.copy_state()
    _first_change(state)["required_artifact_ids"] = ["missing"]
    verify_finding(
        repository.validate(state),
        FindingCode.INVALID_ARTIFACT,
        "active_changes",
        CHANGE_ID,
        "required_artifact_ids",
        "missing",
    )


def verify_a1_c05_exact_commit_object_type(
    repository: RepositoryFixture,
) -> None:
    assert_findings_equal(repository.validate(), frozenset())
    repository.git(
        "tag",
        "-a",
        "accepted-source-tag",
        "-m",
        "test annotated tag",
        repository.source_commit,
    )
    wrong_objects = (
        (
            "annotated tag",
            repository.git("rev-parse", "accepted-source-tag^{tag}"),
        ),
        (
            "tree",
            repository.git("rev-parse", f"{repository.source_commit}^{{tree}}"),
        ),
        (
            "blob",
            repository.git("rev-parse", f"{repository.source_commit}:AGENTS.md"),
        ),
    )
    for kind, object_id in wrong_objects:
        state = repository.copy_state()
        _source(state)["git_commit"] = object_id
        repository.git(
            "cat-file",
            "-t",
            object_id,
            evidence_step=f"Observe exact {kind} Git object type",
            attach_success=True,
        )
        verify_finding(
            repository.validate(state),
            FindingCode.UNRESOLVABLE_REFERENCE,
            "accepted_source_baseline",
            "git_commit",
        )
