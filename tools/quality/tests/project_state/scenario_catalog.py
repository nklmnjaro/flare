from collections.abc import Callable
from functools import partial

from tools.project_state.model import FindingCode
from tools.quality.tests.project_state import artifact_scenarios as artifacts
from tools.quality.tests.project_state import authority_scenarios as authority
from tools.quality.tests.project_state import continuation_scenarios as continuation
from tools.quality.tests.project_state import decoding_scenarios as decoding
from tools.quality.tests.project_state import evidence_scenarios as evidence
from tools.quality.tests.project_state import projection_scenarios as projection
from tools.quality.tests.project_state import repository_scenarios as repository_cases
from tools.quality.tests.project_state.reporting import Area, Scenario
from tools.quality.tests.project_state.support import RepositoryFixture

type Verification = Callable[[RepositoryFixture], None]

_VERIFY: dict[str, Verification] = {
    "n01": decoding.verify_a1_n01_unsupported_schema,
    "n02": decoding.verify_a1_n02_duplicate_json_key,
    "n03a": partial(
        authority.verify_invalid_top_level_reference,
        field="product_phase_ref",
        value="/etc/passwd",
        code=FindingCode.INVALID_PATH,
    ),
    "n03e": partial(
        authority.verify_invalid_top_level_reference,
        field="product_phase_ref",
        value="docs/../../etc/passwd",
        code=FindingCode.INVALID_PATH,
    ),
    "n04s": partial(
        authority.verify_a1_n04_unresolvable_authority,
        target_kind="symlink",
    ),
    "n04u": partial(
        authority.verify_a1_n04_unresolvable_authority,
        target_kind="untracked",
    ),
    "n04m": partial(
        authority.verify_a1_n04_unresolvable_authority,
        target_kind="missing",
    ),
    "n05i": partial(
        authority.verify_a1_n05_wrong_change_identity_or_status,
        defect="wrong-id",
    ),
    "n05s": partial(
        authority.verify_a1_n05_wrong_change_identity_or_status,
        defect="wrong-status",
    ),
    "n06": artifacts.verify_a1_n06_missing_source_commit,
    "n07": artifacts.verify_a1_n07_source_manifest_commit_mismatch,
    "n08": artifacts.verify_a1_n08_artifact_id_collision,
    "n09": artifacts.verify_a1_n09_artifact_sha_mismatch,
    "n10": artifacts.verify_a1_n10_required_artifact_unresolved,
    "n11z": partial(authority.verify_a1_n11_integrator_resolution, principal_count=0),
    "n11m": partial(authority.verify_a1_n11_integrator_resolution, principal_count=2),
    "n12": authority.verify_a1_n12_superseded_integrator_assignment,
    "n13": authority.verify_a1_n13_missing_change_contract,
    "n14n": partial(authority.verify_a1_n14_non_active_change, status="NOT READY"),
    "n14r": partial(authority.verify_a1_n14_non_active_change, status="REVOKED"),
    "n14s": partial(authority.verify_a1_n14_non_active_change, status="SUPERSEDED"),
    "n15": continuation.verify_a1_n15_blocker_unknown_change,
    "n16": continuation.verify_a1_n16_unknown_next_action,
    "n17": continuation.verify_a1_n17_blocked_next_action,
    "n18": continuation.verify_a1_n18_non_actionable_change,
    "n19": continuation.verify_a1_n19_no_next_action_explanation,
    "n20": authority.verify_a1_n20_invalid_enforcement_matrix,
    "n21": partial(
        authority.verify_invalid_top_level_reference,
        field="production_gate_ref",
        value="docs/lookalike-production-gate.md",
        code=FindingCode.UNRESOLVABLE_REFERENCE,
        lookalike="# Accepted test production gate\n",
    ),
    "n22": partial(
        authority.verify_invalid_top_level_reference,
        field="product_phase_ref",
        value="docs/lookalike-product-phase.md",
        code=FindingCode.UNRESOLVABLE_REFERENCE,
        lookalike="# Accepted test product phase\n",
    ),
    "n23": projection.verify_a1_n23_projection_from_other_candidate,
    "n24": decoding.verify_a1_n24_deterministic_finding_set,
    "n25": decoding.verify_a1_n25_explicit_truncation,
    "n30": authority.verify_a1_n30_worktree_only_reference,
    "c01": repository_cases.verify_a1_c01_movable_ref_is_pinned,
    "c02": decoding.verify_a1_c02_schema_authenticity,
    "c03": decoding.verify_a1_c03_validation_stage_order,
    "c04": authority.verify_a1_c04_structured_change_authority,
    "c05": artifacts.verify_a1_c05_exact_commit_object_type,
    "c06": authority.verify_a1_c06_unsafe_reference_lexemes,
    "c07": repository_cases.verify_a1_c07_canonical_candidate_passes,
    "c08": evidence.verify_a1_c08_cli_exit_contract,
    "c09": evidence.verify_a1_c09_command_evidence_policy,
}

V = Area.VALIDATION
R = Area.REFERENCE
P = Area.PROJECTION
E = Area.EVIDENCE


def _case(
    scenario_id: str,
    title: str,
    area: Area,
    verification: str,
) -> Scenario[RepositoryFixture]:
    return Scenario(scenario_id, title, area, _VERIFY[verification])


VALIDATION_SCENARIOS = (
    _case("A1-N01", "Reject unsupported schema version", V, "n01"),
    _case("A1-N02", "Reject duplicate JSON object key", V, "n02"),
    _case("A1-N03", "Reject absolute repository path", R, "n03a"),
    _case("A1-N03", "Reject root-escaping path", R, "n03e"),
    _case("A1-N04", "Reject symlink authority", R, "n04s"),
    _case("A1-N04", "Reject untracked authority", R, "n04u"),
    _case("A1-N04", "Reject missing authority", R, "n04m"),
    _case("A1-N05", "Reject wrong Change identity", R, "n05i"),
    _case("A1-N05", "Reject wrong Change status", R, "n05s"),
    _case("A1-N06", "Reject missing source commit", R, "n06"),
    _case("A1-N07", "Reject mismatched source manifest", R, "n07"),
    _case("A1-N08", "Reject duplicate artifact identity", R, "n08"),
    _case("A1-N09", "Reject artifact SHA mismatch", R, "n09"),
    _case("A1-N10", "Reject unresolved required artifact", R, "n10"),
    _case("A1-N11", "Reject zero Integrator principals", R, "n11z"),
    _case("A1-N11", "Reject multiple Integrator principals", R, "n11m"),
    _case("A1-N12", "Reject superseded Integrator assignment", R, "n12"),
    _case("A1-N13", "Reject missing Change contract", R, "n13"),
    _case("A1-N14", "Reject not-ready Change", R, "n14n"),
    _case("A1-N14", "Reject revoked Change", R, "n14r"),
    _case("A1-N14", "Reject superseded Change", R, "n14s"),
    _case("A1-N15", "Reject blocker for unknown Change", R, "n15"),
    _case("A1-N16", "Reject unknown next action", V, "n16"),
    _case("A1-N17", "Reject blocked next action", V, "n17"),
    _case("A1-N18", "Reject non-actionable next action", V, "n18"),
    _case("A1-N19", "Reject no-action without explanation", V, "n19"),
    _case("A1-N20", "Reject invalid enforcement matrix", R, "n20"),
    _case("A1-N21", "Reject production-gate lookalike", R, "n21"),
    _case("A1-N22", "Reject product-phase lookalike", R, "n22"),
    _case("A1-N23", "Reject projection from another candidate", P, "n23"),
    _case("A1-N24", "Deduplicate deterministic findings", V, "n24"),
    _case("A1-N25", "Expose finding truncation", V, "n25"),
    _case("A1-N30", "Reject worktree-only reference", R, "n30"),
    _case("A1-C01", "Pin a movable validation ref to one tree", V, "c01"),
    _case("A1-C02", "Reject candidate schema self-authentication", V, "c02"),
    _case("A1-C03", "Preserve raw JSON validation stage precedence", V, "c03"),
    _case("A1-C04", "Reject Markdown authority lookalikes", R, "c04"),
    _case("A1-C05", "Require an exact commit object baseline", R, "c05"),
    _case("A1-C06", "Reject unsafe reference lexemes", R, "c06"),
    _case("A1-C07", "Validate the exact canonical candidate", V, "c07"),
    _case("A1-C08", "Enforce CLI result and exit semantics", E, "c08"),
    _case("A1-C09", "Prove bounded redacted command evidence", E, "c09"),
)
