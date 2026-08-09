import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

from tools.project_state.model import (
    CandidateDefect,
    JSONValue,
    PreparedCandidate,
    PublicationResult,
    PublicationStatus,
)
from tools.project_state.publication import (
    prepare_candidate,
    publish_candidate,
)
from tools.project_state.validation import (
    PROJECTION_PATH,
    STATE_PATH,
    validate_candidate,
)
from tools.quality.tests.project_state.assertions import (
    assert_equal,
    assert_publication_status,
    assert_true,
    assert_validation_passes,
)
from tools.quality.tests.project_state.reporting import (
    Area,
    Scenario,
    attach_json,
    step_context,
)
from tools.quality.tests.project_state.support import RepositoryFixture, json_bytes


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _prepared(
    repository: RepositoryFixture,
    state: dict[str, JSONValue] | None = None,
    *,
    parent: str | None = None,
) -> PreparedCandidate:
    with step_context("Prepare and validate immutable candidate commit"):
        prepared = prepare_candidate(
            repository.root,
            repository.parent if parent is None else parent,
            json_bytes(repository.state if state is None else state),
        )
        if isinstance(prepared, CandidateDefect):
            labels = sorted(
                f"{finding.code.value}:{finding.context}"
                for finding in prepared.findings
            )
            attach_json(
                "candidate defects",
                [finding.as_dict() for finding in prepared.findings],
            )
            raise TypeError(f"expected prepared candidate, got defects {labels}")
        attach_json(
            "prepared candidate identity",
            {
                "candidate_coordination_commit": prepared.candidate_coordination_commit,
                "candidate_state_sha256": prepared.candidate_state_sha256,
                "expected_coordination_parent_commit": (
                    prepared.expected_coordination_parent_commit
                ),
            },
        )
        return prepared


def _verify_movable_candidate_cannot_publish_moved_target(
    repository: RepositoryFixture,
) -> None:
    prepared = _prepared(repository)
    repository.git(
        "branch",
        "candidate",
        prepared.candidate_coordination_commit,
    )
    repository.write(STATE_PATH, b'{"invalid":true}\n')
    repository.write(PROJECTION_PATH, b"invalid\n")
    invalid_commit = repository.commit_paths(
        "test: create invalid movable target",
        STATE_PATH,
        PROJECTION_PATH,
    )
    repository.git(
        "update-ref",
        "refs/heads/coordination",
        repository.parent,
        invalid_commit,
    )

    def move_candidate_ref() -> None:
        with step_context("Move candidate alias after validation and before CAS"):
            repository.git(
                "update-ref",
                "refs/heads/candidate",
                invalid_commit,
                prepared.candidate_coordination_commit,
            )

    with step_context("Publish using the candidate OID pinned before validation"):
        result = publish_candidate(
            repository.root,
            "refs/heads/coordination",
            repository.parent,
            _sha256(json_bytes(repository.state)),
            "refs/heads/candidate",
            before_cas=move_candidate_ref,
        )
        attach_json("movable candidate publication evidence", result.as_dict())
    assert_publication_status(result, PublicationStatus.PASS)
    assert_equal(
        result.candidate_coordination_commit,
        prepared.candidate_coordination_commit,
        "pinned candidate evidence OID",
    )
    assert_equal(
        repository.git(
            "rev-parse",
            "coordination",
            evidence_step="Observe published canonical coordination OID",
            attach_success=True,
        ),
        prepared.candidate_coordination_commit,
        "canonical ref pinned to validated candidate OID",
    )
    assert_equal(
        repository.git("rev-parse", "candidate"),
        invalid_commit,
        "moved candidate alias",
    )


def verify_a1_n26_stale_state_sha(repository: RepositoryFixture) -> None:
    prepared = _prepared(repository)
    assert_true(isinstance(prepared, PreparedCandidate), "PreparedCandidate type")
    with step_context("Attempt publication with a stale state SHA preimage"):
        result = publish_candidate(
            repository.root,
            "refs/heads/coordination",
            repository.parent,
            "0" * 64,
            prepared.candidate_coordination_commit,
        )
        attach_json("publication evidence", result.as_dict())
    assert_publication_status(result, PublicationStatus.STALE_PREIMAGE)
    assert_equal(
        repository.git("rev-parse", "coordination"),
        repository.parent,
        "unchanged coordination ref",
    )


def verify_a1_n27_moved_ref_same_state(repository: RepositoryFixture) -> None:
    prepared = _prepared(repository)
    source_sha = _sha256(json_bytes(repository.state))
    repository.write("unrelated.txt", "ref moved; state unchanged\n")
    moved = repository.commit_all("test: move coordination ref")
    with step_context("Attempt publication after the canonical ref moved"):
        result = publish_candidate(
            repository.root,
            "refs/heads/coordination",
            repository.parent,
            source_sha,
            prepared.candidate_coordination_commit,
        )
        attach_json("moved ref evidence", result.as_dict())
    assert_publication_status(result, PublicationStatus.STALE_PREIMAGE)
    assert_equal(
        repository.git(
            "rev-parse",
            "coordination",
            evidence_step="Observe moved coordination ref",
            attach_success=True,
        ),
        moved,
        "already-moved coordination ref",
    )


def verify_a1_n28_single_race_winner(repository: RepositoryFixture) -> None:
    first_state = repository.copy_state()
    second_state = repository.copy_state()
    baseline = second_state.get("accepted_source_baseline")
    if not isinstance(baseline, dict):
        raise TypeError("accepted_source_baseline must be an object")
    baseline["git_commit"] = repository.parent
    first = _prepared(repository, first_state)
    second = _prepared(repository, second_state)
    expected_sha = _sha256(json_bytes(repository.state))
    barrier = threading.Barrier(2)

    def await_race() -> None:
        barrier.wait()

    def publish(commit: str) -> PublicationResult:
        return publish_candidate(
            repository.root,
            "refs/heads/coordination",
            repository.parent,
            expected_sha,
            commit,
            before_cas=await_race,
        )

    with step_context("Race two publications against one immutable CAS preimage"):
        attach_json(
            "CAS race inputs",
            {
                "candidate_oids": [
                    first.candidate_coordination_commit,
                    second.candidate_coordination_commit,
                ],
                "expected_parent_oid": repository.parent,
                "expected_state_sha256": expected_sha,
            },
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(publish, commit)
                for commit in (
                    first.candidate_coordination_commit,
                    second.candidate_coordination_commit,
                )
            ]
            results = [future.result(timeout=10) for future in futures]
        attach_json(
            "bounded race results",
            [result.as_dict() for result in results],
        )
    statuses = sorted(result.result.value for result in results)
    assert_equal(
        statuses,
        [PublicationStatus.PASS.value, PublicationStatus.STALE_PREIMAGE.value],
        "race publication outcomes",
    )
    winner = repository.git("rev-parse", "coordination")
    assert_true(
        winner
        in {first.candidate_coordination_commit, second.candidate_coordination_commit},
        "published race winner identity",
    )
    assert_validation_passes(validate_candidate(repository.tree(winner)).result)


def verify_a1_n29_rebased_candidate(repository: RepositoryFixture) -> None:
    original = repository.parent
    repository.write("unrelated.txt", "new parent\n")
    moved = repository.commit_all("test: move parent")
    rebased = _prepared(repository, parent=moved)
    with step_context("Attempt publication of a candidate based on another parent"):
        result = publish_candidate(
            repository.root,
            "refs/heads/coordination",
            original,
            _sha256(json_bytes(repository.state)),
            rebased.candidate_coordination_commit,
        )
        attach_json("rebased candidate evidence", result.as_dict())
    assert_publication_status(result, PublicationStatus.INVALID_CANDIDATE)
    assert_equal(
        repository.git("rev-parse", "coordination"),
        moved,
        "unchanged moved coordination ref",
    )


PUBLICATION_SCENARIOS = (
    Scenario(
        "A1-N27",
        "Pin a movable candidate alias to one OID",
        Area.PUBLICATION,
        _verify_movable_candidate_cannot_publish_moved_target,
    ),
    Scenario(
        "A1-N26",
        "Reject stale state SHA preimage",
        Area.PUBLICATION,
        verify_a1_n26_stale_state_sha,
    ),
    Scenario(
        "A1-N27",
        "Reject moved ref with identical state",
        Area.PUBLICATION,
        verify_a1_n27_moved_ref_same_state,
    ),
    Scenario(
        "A1-N28",
        "Allow one CAS race winner",
        Area.CONCURRENCY,
        verify_a1_n28_single_race_winner,
    ),
    Scenario(
        "A1-N29",
        "Reject rebased candidate",
        Area.PUBLICATION,
        verify_a1_n29_rebased_candidate,
    ),
)
