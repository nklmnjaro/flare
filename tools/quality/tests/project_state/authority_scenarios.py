from tools.project_state.model import FindingCode, JSONValue
from tools.quality.tests.project_state.assertions import (
    assert_equal,
    assert_findings_equal,
)
from tools.quality.tests.project_state.support import (
    CHANGE_ID,
    CHANGE_REF,
    RepositoryFixture,
    json_array,
    json_bytes,
    json_object,
)
from tools.quality.tests.project_state.validation_scenario_support import (
    CHANGE_CONTEXT,
    verify_finding,
    verify_finding_at,
)


def _first_change(state: dict[str, JSONValue]) -> dict[str, JSONValue]:
    changes = json_array(state.get("active_changes"), "active changes")
    return json_object(changes[0], "first active change")


def verify_invalid_top_level_reference(
    repository: RepositoryFixture,
    field: str,
    value: str,
    code: FindingCode,
    lookalike: str = "",
) -> None:
    if lookalike:
        repository.write(value, lookalike)
        repository.commit_all(f"test: add {field} lookalike")
    state = repository.copy_state()
    state[field] = value
    verify_finding(repository.validate(state), code, field)


def verify_a1_n04_unresolvable_authority(
    repository: RepositoryFixture,
    target_kind: str,
) -> None:
    if target_kind == "symlink":
        reference = repository.add_authority_symlink()
    elif target_kind == "untracked":
        reference = "docs/untracked.md"
        repository.write(reference, "# Lookalike current product phase\n")
    else:
        reference = "docs/missing.md"
    state = repository.copy_state()
    state["product_phase_ref"] = reference
    verify_finding(
        repository.validate(state),
        FindingCode.UNRESOLVABLE_REFERENCE,
        "product_phase_ref",
    )


def verify_a1_n05_wrong_change_identity_or_status(
    repository: RepositoryFixture,
    defect: str,
) -> None:
    change_id = "OTHER" if defect == "wrong-id" else CHANGE_ID
    status = (
        "COMPLETED" if defect == "wrong-status" else "ACCEPTED / READY FOR BOUNDED CODE"
    )
    repository.write(
        CHANGE_REF,
        "---\n"
        f'change_id: "{change_id}"\n'
        f'status: "{status}"\n'
        'implementation_authorization: "AUTHORIZED"\n'
        "---\n\n# Change\n",
    )
    repository.commit_all("test: invalidate Change metadata")
    verify_finding_at(repository.validate(), FindingCode.INVALID_CHANGE, CHANGE_CONTEXT)
    if defect == "wrong-id":
        lookalike = "docs/lookalike-change.md"
        repository.write(
            lookalike,
            "---\n"
            f'change_id: "{CHANGE_ID}"\n'
            'status: "ACCEPTED / READY FOR BOUNDED CODE"\n'
            'implementation_authorization: "AUTHORIZED"\n'
            "---\n\n# Change\n",
        )
        repository.commit_all("test: add Change metadata lookalike")
        state = repository.copy_state()
        _first_change(state)["contract_ref"] = lookalike
        verify_finding_at(
            repository.validate(state),
            FindingCode.INVALID_CHANGE,
            CHANGE_CONTEXT,
        )


def verify_a1_n11_integrator_resolution(
    repository: RepositoryFixture,
    principal_count: int,
) -> None:
    principals = ", ".join(f'"principal-{index}"' for index in range(principal_count))
    repository.write(
        "tools/platform/team_dispatch/config.toml",
        "\n".join(
            (
                *(
                    f"[principals.principal-{index}]\n"
                    f'display = "Synthetic principal {index}"\n'
                    'status = "current"\n'
                    for index in range(principal_count)
                ),
                "[roles.integrator]",
                f"principal_refs = [{principals}]",
                "",
            )
        ),
    )
    repository.commit_all("test: invalidate Integrator principal resolution")
    verify_finding(
        repository.validate(),
        FindingCode.INVALID_INTEGRATOR,
        "integrator",
        "assignee_ref",
    )


def verify_a1_n12_superseded_integrator_assignment(
    repository: RepositoryFixture,
) -> None:
    assignment: dict[str, JSONValue] = {
        "assignment_id": "A1-INTEGRATOR",
        "assignment_kind": "integrator",
        "assignee_ref": "integrator",
        "superseded": True,
    }
    assignment_ref = json_object(repository.state.get("integrator"), "integrator")[
        "assignment_ref"
    ]
    if not isinstance(assignment_ref, str):
        raise TypeError("assignment_ref must be a string")
    repository.write(assignment_ref, json_bytes(assignment))
    repository.commit_all("test: supersede Integrator assignment")
    verify_finding(
        repository.validate(),
        FindingCode.INVALID_INTEGRATOR,
        "integrator",
        "assignment_ref",
    )


def verify_a1_n13_missing_change_contract(repository: RepositoryFixture) -> None:
    repository.remove_and_commit(CHANGE_REF, "test: remove accepted Change contract")
    verify_finding_at(
        repository.validate(),
        FindingCode.UNRESOLVABLE_REFERENCE,
        CHANGE_CONTEXT,
    )


def verify_a1_n14_non_active_change(
    repository: RepositoryFixture,
    status: str,
) -> None:
    repository.write(
        CHANGE_REF,
        "---\n"
        f'change_id: "{CHANGE_ID}"\n'
        f'status: "{status}"\n'
        'implementation_authorization: "AUTHORIZED"\n'
        "---\n\n# Change\n\nMisleading prose says READY FOR BOUNDED CODE.\n",
    )
    repository.commit_all("test: make Change non-active")
    verify_finding_at(repository.validate(), FindingCode.INVALID_CHANGE, CHANGE_CONTEXT)


def verify_a1_n20_invalid_enforcement_matrix(
    repository: RepositoryFixture,
) -> None:
    reference = (
        "docs/engineering/governance/rc2/FLARE_ENFORCEMENT_MATRIX_v0.2_20260807.md"
    )
    repository.write(
        reference,
        '---\ndocument_id: "WRONG"\n'
        'status: "INITIAL TRACEABILITY CLASSIFICATION FOR CURRENT SCAFFOLD"\n---\n',
    )
    repository.commit_all("test: invalidate enforcement matrix identity")
    verify_finding(
        repository.validate(),
        FindingCode.UNRESOLVABLE_REFERENCE,
        "enforcement_matrix_ref",
    )
    repository.write(
        reference,
        '---\ndocument_id: "FLARE-ENFORCEMENT-MATRIX-0001"\nstatus: "OLD"\n---\n',
    )
    repository.commit_all("test: invalidate enforcement matrix status")
    verify_finding(
        repository.validate(),
        FindingCode.UNRESOLVABLE_REFERENCE,
        "enforcement_matrix_ref",
    )


def verify_a1_n30_worktree_only_reference(repository: RepositoryFixture) -> None:
    reference = "docs/decisions/untracked.md"
    repository.write(
        reference,
        '---\ndocument_id: "LOCAL"\nstatus: "OPEN"\n'
        f'blocks_change_ids: "{CHANGE_ID}"\n---\n',
    )
    status = repository.git(
        "status",
        "--short",
        "--",
        reference,
        evidence_step="Observe reference exists only in the working tree",
        attach_success=True,
    )
    assert_equal(status, f"?? {reference}", "worktree-only Git status")
    state = repository.copy_state()
    decisions = json_object(state.get("open_decisions"), "open decisions")
    decisions["technical"] = [reference]
    verify_finding(
        repository.validate(state),
        FindingCode.UNRESOLVABLE_REFERENCE,
        "open_decisions",
        "technical",
        reference,
    )


def verify_a1_c04_structured_change_authority(
    repository: RepositoryFixture,
) -> None:
    assert_findings_equal(repository.validate(), frozenset())
    accepted_metadata = (
        "---\n"
        f'change_id: "{CHANGE_ID}"\n'
        'status: "ACCEPTED / READY FOR BOUNDED CODE"\n'
        'implementation_authorization: "AUTHORIZED"\n'
        "---"
    )
    repository.write(
        CHANGE_REF,
        f"# Documentation example\n\n```markdown\n{accepted_metadata}\n```\n",
    )
    repository.commit_all("test: place Change metadata in a fenced example")
    verify_finding_at(repository.validate(), FindingCode.INVALID_CHANGE, CHANGE_CONTEXT)

    repository.write(
        CHANGE_REF,
        f"# Documentation example\n\nThe following is only an example:\n\n{accepted_metadata}\n",
    )
    repository.commit_all("test: place Change metadata in body prose")
    verify_finding_at(repository.validate(), FindingCode.INVALID_CHANGE, CHANGE_CONTEXT)


def verify_a1_c06_unsafe_reference_lexemes(
    repository: RepositoryFixture,
) -> None:
    assert_findings_equal(repository.validate(), frozenset())
    for reference in (
        "docs/decisions/unsafe\x00.md",
        "docs/decisions/unsafe\x1f.md",
        "docs//decisions/open.md",
        "docs\\decisions\\open.md",
    ):
        state = repository.copy_state()
        decisions = json_object(state.get("open_decisions"), "open decisions")
        decisions["technical"] = [reference]
        verify_finding(
            repository.validate(state),
            FindingCode.INVALID_PATH,
            "open_decisions",
            "technical",
            reference,
        )

    valid = repository.copy_state()
    decisions = json_object(valid.get("open_decisions"), "open decisions")
    decisions["technical"] = ["docs/decisions/open.md"]
    assert_findings_equal(repository.validate(valid), frozenset())
