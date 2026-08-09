from tools.project_state.decoding import decode_state
from tools.project_state.model import FindingCode
from tools.project_state.projection import render_projection
from tools.project_state.validation import PROJECTION_PATH, SCHEMA_PATH
from tools.quality.tests.project_state.assertions import assert_equal, assert_true
from tools.quality.tests.project_state.support import PROJECT_ROOT, RepositoryFixture
from tools.quality.tests.project_state.validation_scenario_support import (
    finding,
    verify_only,
)


def verify_a1_n23_projection_from_other_candidate(
    repository: RepositoryFixture,
) -> None:
    corpus_raw = (PROJECT_ROOT / "docs/project/state.json").read_bytes()
    corpus = decode_state(
        corpus_raw,
        (PROJECT_ROOT / SCHEMA_PATH).read_bytes(),
    ).state
    if corpus is None:
        raise TypeError("accepted projection corpus state must decode")
    stored_projection = (PROJECT_ROOT / PROJECTION_PATH).read_bytes()
    assert_equal(
        render_projection(corpus),
        stored_projection,
        "projection against independently stored accepted corpus",
    )
    rendered_text = stored_projection.decode("utf-8", "strict")
    guaranteed_fragments = (
        corpus.project_id,
        corpus.schema_version,
        corpus.accepted_source_baseline.git_commit,
        corpus.product_phase_ref,
        corpus.production_gate_ref,
        corpus.integrator.assignee_ref,
        *(change.change_id for change in corpus.active_changes),
        *corpus.next_action_change_ids,
        *(blocker.blocker_id for blocker in corpus.open_blockers),
    )
    for fragment in guaranteed_fragments:
        assert_true(fragment in rendered_text, f"bounded projection renders {fragment}")
    assert_true(
        corpus.integrator.assignment_ref not in rendered_text,
        "bounded projection does not claim full state recovery",
    )
    accepted_projection = (repository.root / PROJECTION_PATH).read_bytes()
    other_projection = accepted_projection.replace(
        repository.source_commit.encode(),
        repository.parent.encode(),
    )
    verify_only(
        repository.validate(projection=other_projection),
        finding(FindingCode.PROJECTION_MISMATCH, "projection"),
    )
    candidate = repository.remove_and_commit(PROJECTION_PATH, "test: remove projection")
    verify_only(
        repository.observe_candidate(candidate),
        finding(FindingCode.PROJECTION_MISMATCH, "projection"),
    )
