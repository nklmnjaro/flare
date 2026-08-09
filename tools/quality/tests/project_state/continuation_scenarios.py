from tools.project_state.model import FindingCode
from tools.quality.tests.project_state.support import (
    CHANGE_ID,
    CHANGE_REF,
    RepositoryFixture,
)
from tools.quality.tests.project_state.validation_scenario_support import (
    CHANGE_CONTEXT,
    verify_finding,
    verify_finding_at,
)


def verify_a1_n15_blocker_unknown_change(repository: RepositoryFixture) -> None:
    state = repository.copy_state()
    state["open_blockers"] = [
        {
            "blocker_id": "BLOCK-1",
            "blocker_ref": "docs/blockers/open.md",
            "blocks_change_ids": ["UNKNOWN"],
        }
    ]
    verify_finding(
        repository.validate(state),
        FindingCode.INVALID_CHANGE,
        "open_blockers",
        "BLOCK-1",
        "blocks_change_ids",
        "UNKNOWN",
    )


def verify_a1_n16_unknown_next_action(repository: RepositoryFixture) -> None:
    state = repository.copy_state()
    state["next_action_change_ids"] = ["UNKNOWN"]
    verify_finding(
        repository.validate(state),
        FindingCode.INVALID_NEXT_ACTION,
        "next_action_change_ids",
        "UNKNOWN",
    )


def verify_a1_n17_blocked_next_action(repository: RepositoryFixture) -> None:
    state = repository.copy_state()
    state["open_blockers"] = [
        {
            "blocker_id": "BLOCK-1",
            "blocker_ref": "docs/blockers/open.md",
            "blocks_change_ids": [CHANGE_ID],
        }
    ]
    verify_finding(
        repository.validate(state),
        FindingCode.INVALID_NEXT_ACTION,
        "next_action_change_ids",
        CHANGE_ID,
    )


def verify_a1_n18_non_actionable_change(repository: RepositoryFixture) -> None:
    repository.write(
        CHANGE_REF,
        "---\n"
        f'change_id: "{CHANGE_ID}"\n'
        'status: "NOT READY"\n'
        'implementation_authorization: "AUTHORIZED"\n'
        "---\n\n# Change\n",
    )
    repository.commit_all("test: remove Change authorization")
    verify_finding(
        repository.validate(),
        FindingCode.INVALID_NEXT_ACTION,
        "next_action_change_ids",
        CHANGE_ID,
    )
    repository.write(
        CHANGE_REF,
        "---\n"
        f'change_id: "{CHANGE_ID}"\n'
        'status: "ACCEPTED / READY FOR BOUNDED CODE"\n'
        'implementation_authorization: "DENIED"\n'
        "---\n\n# Change\n",
    )
    repository.commit_all("test: deny implementation explicitly")
    verify_finding_at(
        repository.validate(),
        FindingCode.INVALID_CHANGE,
        CHANGE_CONTEXT,
    )


def verify_a1_n19_no_next_action_explanation(
    repository: RepositoryFixture,
) -> None:
    state = repository.copy_state()
    state["next_action_change_ids"] = []
    verify_finding(
        repository.validate(state),
        FindingCode.INVALID_NEXT_ACTION,
        "next_action_change_ids",
    )
    state["open_blockers"] = [
        {
            "blocker_id": "BLOCK-1",
            "blocker_ref": "docs/blockers/open.md",
            "blocks_change_ids": ["UNKNOWN"],
        }
    ]
    verify_finding(
        repository.validate(state),
        FindingCode.INVALID_NEXT_ACTION,
        "next_action_change_ids",
    )
