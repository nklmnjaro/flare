import hashlib

from pydantic import ValidationError

from tools.project_state.json_codec import (
    DuplicateKeyError,
    StrictJSONError,
    parse_strict_json,
)
from tools.project_state.model import (
    AcceptedArtifact,
    ArtifactManifest,
    CoordinationState,
    FindingCode,
    FindingCollector,
)
from tools.project_state.pointer import json_pointer
from tools.project_state.reference_validation import read_reference
from tools.project_state.repository import TreeReader


def _read_manifest(
    tree: TreeReader,
    artifact: AcceptedArtifact,
    context: str,
    findings: FindingCollector,
) -> ArtifactManifest | None:
    raw = read_reference(tree, artifact.manifest_ref, context, findings)
    if raw is None:
        return None
    try:
        return ArtifactManifest.model_validate(parse_strict_json(raw))
    except DuplicateKeyError, StrictJSONError, ValidationError:
        findings.add(
            FindingCode.INVALID_ARTIFACT,
            context,
            "manifest is not strict typed JSON",
        )
        return None


def _validate_artifacts(
    artifacts: tuple[AcceptedArtifact, ...],
    tree: TreeReader,
    findings: FindingCollector,
) -> tuple[set[str], dict[str, ArtifactManifest]]:
    artifact_ids: set[str] = set()
    manifests: dict[str, ArtifactManifest] = {}
    for artifact in artifacts:
        context = json_pointer("accepted_artifacts", artifact.artifact_id)
        if artifact.artifact_id in artifact_ids:
            findings.add(
                FindingCode.INVALID_ARTIFACT,
                f"{context}/artifact_id",
                "artifact ID collision",
            )
        artifact_ids.add(artifact.artifact_id)
        manifest = _read_manifest(
            tree,
            artifact,
            f"{context}/manifest_ref",
            findings,
        )
        if manifest is None:
            continue
        manifests[artifact.artifact_id] = manifest
        if (
            manifest.artifact_id != artifact.artifact_id
            or manifest.kind != artifact.kind
            or manifest.sha256 != artifact.sha256
        ):
            findings.add(
                FindingCode.INVALID_ARTIFACT,
                context,
                "state and manifest metadata differ",
            )
        content = read_reference(
            tree,
            manifest.artifact_ref,
            json_pointer(
                "accepted_artifacts",
                artifact.artifact_id,
                "manifest_ref",
                "artifact_ref",
            ),
            findings,
        )
        if (
            content is not None
            and hashlib.sha256(content).hexdigest() != artifact.sha256
        ):
            findings.add(
                FindingCode.SHA_MISMATCH,
                f"{context}/sha256",
                artifact.artifact_id,
            )
    return artifact_ids, manifests


def validate_artifacts_and_baseline(
    state: CoordinationState,
    tree: TreeReader,
    findings: FindingCollector,
) -> None:
    artifact_ids, manifests = _validate_artifacts(
        state.accepted_artifacts,
        tree,
        findings,
    )
    baseline = state.accepted_source_baseline
    if not tree.commit_exists(baseline.git_commit):
        findings.add(
            FindingCode.UNRESOLVABLE_REFERENCE,
            json_pointer("accepted_source_baseline", "git_commit"),
            "source commit does not exist",
        )
    if baseline.source_artifact_id is not None:
        manifest = manifests.get(baseline.source_artifact_id)
        if baseline.source_artifact_id not in artifact_ids or manifest is None:
            findings.add(
                FindingCode.INVALID_ARTIFACT,
                json_pointer("accepted_source_baseline", "source_artifact_id"),
                "source artifact is unresolved",
            )
        elif manifest.source_git_commit != baseline.git_commit:
            findings.add(
                FindingCode.CONTRADICTION,
                json_pointer("accepted_source_baseline", "source_artifact_id"),
                "manifest binds another source commit",
            )
    for change in state.active_changes:
        for artifact_id in change.required_artifact_ids:
            if artifact_id not in artifact_ids or artifact_id not in manifests:
                findings.add(
                    FindingCode.INVALID_ARTIFACT,
                    json_pointer(
                        "active_changes",
                        change.change_id,
                        "required_artifact_ids",
                        artifact_id,
                    ),
                    "required artifact is unresolved",
                )
