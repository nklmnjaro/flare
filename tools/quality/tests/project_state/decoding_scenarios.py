from tools.project_state.decoding import SCHEMA_ID
from tools.project_state.model import Finding, FindingCode, FindingCollector, JSONValue
from tools.project_state.validation import SCHEMA_PATH, STATE_PATH
from tools.quality.tests.project_state.assertions import (
    assert_equal,
    assert_findings_equal,
    assert_validation_summary,
)
from tools.quality.tests.project_state.support import RepositoryFixture, json_bytes
from tools.quality.tests.project_state.validation_scenario_support import (
    finding,
    verify_finding,
    verify_only,
)


def _write_change(repository: RepositoryFixture, change_id: str) -> str:
    reference = f"docs/engineering/changes/{change_id}.md"
    repository.write(
        reference,
        "---\n"
        f'change_id: "{change_id}"\n'
        'status: "ACCEPTED / READY FOR BOUNDED CODE"\n'
        'implementation_authorization: "AUTHORIZED"\n'
        "---\n\n# Change\n",
    )
    return reference


def verify_a1_n01_unsupported_schema(repository: RepositoryFixture) -> None:
    verify_only(
        repository.validate(raw=b'{"schema_version":\n'),
        finding(FindingCode.INVALID_JSON),
    )
    unknown = repository.copy_state()
    unknown["unexpected"] = True
    verify_finding(repository.validate(unknown), FindingCode.SCHEMA_VIOLATION)
    missing = repository.copy_state()
    del missing["schema_version"]
    verify_only(
        repository.validate(missing),
        finding(FindingCode.SCHEMA_VIOLATION),
    )
    wrong_type = repository.copy_state()
    wrong_type["schema_version"] = 1
    verify_only(
        repository.validate(wrong_type),
        finding(FindingCode.SCHEMA_VIOLATION, "schema_version"),
    )
    state = repository.copy_state()
    state["schema_version"] = "2.0"
    verify_only(
        repository.validate(state),
        finding(FindingCode.UNSUPPORTED_SCHEMA, "schema_version"),
    )
    rejecting_schema: dict[str, JSONValue] = {
        "$id": SCHEMA_ID,
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "not": {},
    }
    repository.write(SCHEMA_PATH, json_bytes(rejecting_schema))
    repository.commit_paths("test: bind rejecting candidate schema", SCHEMA_PATH)
    verify_finding(repository.validate(), FindingCode.SCHEMA_VIOLATION, "schema")


def verify_a1_n02_duplicate_json_key(repository: RepositoryFixture) -> None:
    raw = (repository.root / "docs/project/state.json").read_bytes()
    duplicate = raw.replace(
        b'{\n  "accepted_artifacts"',
        b'{\n  "project_id": "flare",\n  "accepted_artifacts"',
    )
    verify_only(
        repository.validate(raw=duplicate),
        finding(FindingCode.DUPLICATE_KEY),
    )


def verify_a1_n24_deterministic_finding_set(
    repository: RepositoryFixture,
) -> None:
    state = repository.copy_state()
    state["next_action_change_ids"] = ["UNKNOWN"]
    state["open_blockers"] = [
        {
            "blocker_id": "BLOCK-1",
            "blocker_ref": "docs/blockers/open.md",
            "blocks_change_ids": ["UNKNOWN"],
        }
    ]
    expected = {
        finding(
            FindingCode.INVALID_CHANGE,
            "open_blockers",
            "BLOCK-1",
            "blocks_change_ids",
            "UNKNOWN",
        ),
        finding(FindingCode.INVALID_NEXT_ACTION, "next_action_change_ids", "UNKNOWN"),
    }
    first = repository.validate(state)
    second = repository.validate(state)
    assert_findings_equal(first, expected)
    assert_findings_equal(second, expected)
    assert_equal(
        first.result.as_dict(),
        second.result.as_dict(),
        "deterministic serialized result",
        observation=first,
    )

    collector = FindingCollector()
    duplicate = Finding(FindingCode.INVALID_CHANGE, "$/same")
    collector.add(duplicate.code, duplicate.context, "z")
    collector.add(duplicate.code, duplicate.context, "a")
    assert_findings_equal(collector.result().findings, {duplicate})

    first_id = "a"
    second_id = "a/required_artifact_ids/b~"
    first_ref = _write_change(repository, first_id)
    second_ref = _write_change(repository, second_id)
    repository.commit_all("test: add collision-resistant Change identifiers")
    collision = repository.copy_state()
    collision["active_changes"] = [
        {
            "change_id": first_id,
            "contract_ref": first_ref,
            "required_artifact_ids": ["b~/required_artifact_ids/c"],
        },
        {
            "change_id": second_id,
            "contract_ref": second_ref,
            "required_artifact_ids": ["c"],
        },
    ]
    collision["next_action_change_ids"] = [first_id, second_id]
    observation = repository.validate(collision)
    contexts = {
        item.context
        for item in observation.result.findings
        if item.code is FindingCode.INVALID_ARTIFACT
    }
    assert_equal(
        len(contexts),
        2,
        "distinct escaped finding contexts",
        observation=observation,
    )


def verify_a1_n25_explicit_truncation(repository: RepositoryFixture) -> None:
    state = repository.copy_state()
    state["next_action_change_ids"] = ["UNKNOWN"]
    state["open_blockers"] = [
        {
            "blocker_id": "BLOCK-1",
            "blocker_ref": "docs/missing-blocker.md",
            "blocks_change_ids": ["UNKNOWN"],
        }
    ]
    result = repository.validate(state, max_findings=1)
    assert_validation_summary(result, total=3, truncated=True)
    verify_only(
        result,
        finding(
            FindingCode.INVALID_CHANGE,
            "open_blockers",
            "BLOCK-1",
            "blocks_change_ids",
            "UNKNOWN",
        ),
    )


def verify_a1_c02_schema_authenticity(repository: RepositoryFixture) -> None:
    assert_findings_equal(repository.validate(), frozenset())

    invalid_project = repository.copy_state()
    invalid_project["project_id"] = "not-flare"
    weakened: dict[str, JSONValue] = {
        "$id": SCHEMA_ID,
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
    }
    repository.write(SCHEMA_PATH, json_bytes(weakened))
    repository.commit_paths("test: weaken same-ID schema", SCHEMA_PATH)
    verify_finding(
        repository.validate(invalid_project),
        FindingCode.SCHEMA_VIOLATION,
        "schema",
    )

    missing_required = repository.copy_state()
    del missing_required["schema_version"]
    no_required: dict[str, JSONValue] = {
        "$id": SCHEMA_ID,
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "properties": {"project_id": {"type": "string"}},
        "type": "object",
    }
    repository.write(SCHEMA_PATH, json_bytes(no_required))
    repository.commit_paths("test: remove required schema constraints", SCHEMA_PATH)
    verify_finding(
        repository.validate(missing_required),
        FindingCode.SCHEMA_VIOLATION,
        "schema",
    )

    external: dict[str, JSONValue] = {
        "$id": SCHEMA_ID,
        "$ref": "file:///definitely/missing/flare-schema.json",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
    }
    repository.write(SCHEMA_PATH, json_bytes(external))
    repository.commit_paths("test: add unrestricted external schema ref", SCHEMA_PATH)
    verify_finding(
        repository.validate(),
        FindingCode.SCHEMA_VIOLATION,
        "schema",
    )


def verify_a1_c03_validation_stage_order(repository: RepositoryFixture) -> None:
    repository.write(STATE_PATH, b'{"schema_version":\n')
    repository.git("rm", "-q", "--", SCHEMA_PATH)
    candidate = repository.commit_paths(
        "test: combine malformed state with missing schema",
        STATE_PATH,
    )
    verify_only(
        repository.observe_candidate(candidate),
        finding(FindingCode.INVALID_JSON),
    )
