import copy
import hashlib
import os
import shutil
import sys
from pathlib import Path

from tools.project_state.authority import (
    ENFORCEMENT_MATRIX_REF,
    PRODUCT_PHASE_REF,
    PRODUCTION_GATE_REF,
    ROLE_REGISTRY_REF,
)
from tools.project_state.decoding import decode_state
from tools.project_state.git import run_git
from tools.project_state.json_codec import canonical_json_bytes, parse_strict_json
from tools.project_state.model import JSONValue
from tools.project_state.projection import render_projection
from tools.project_state.repository import GitTree
from tools.project_state.validation import (
    PROJECTION_PATH,
    SCHEMA_PATH,
    STATE_PATH,
    validate_candidate,
)
from tools.quality.source_manifest import build_git_source_manifest
from tools.quality.tests.project_state.command_evidence import (
    ValidationObservation,
    run_command,
)
from tools.quality.tests.project_state.reporting import (
    attach_json,
    attach_text,
    step_context,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
CORPUS = Path(__file__).with_name("corpus")
CHANGE_ID = "FLARE-TRACK-A1-COORDINATION-STATE-001"
CHANGE_REF = "docs/engineering/changes/FLARE-TRACK-A1-COORDINATION-STATE-001.md"
ASSIGNMENT_REF = "docs/engineering/team/integrator-assignment.json"


def json_bytes(value: JSONValue) -> bytes:
    return canonical_json_bytes(value)


def json_object(value: JSONValue | None, context: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise TypeError(f"{context} must be an object")
    return value


def json_array(value: JSONValue | None, context: str) -> list[JSONValue]:
    if not isinstance(value, list):
        raise TypeError(f"{context} must be an array")
    return value


def _git_text(
    root: Path,
    *args: str,
    evidence_step: str | None = None,
    attach_success: bool = False,
) -> str:
    result = run_command(
        ("git", "-C", str(root), *args),
        step_title=evidence_step,
        attach_success=attach_success,
    )
    return result.stdout.strip()


def observe_candidate_tree(
    repo: Path,
    candidate: str,
    max_findings: int | None = None,
) -> ValidationObservation:
    tree = GitTree.resolve(repo, candidate)
    if tree is None:
        raise RuntimeError(f"candidate does not resolve to a commit: {candidate}")
    with step_context("Validate exact candidate tree"):
        result = validate_candidate(tree, max_findings).result
        attach_json("bounded validation result", result.as_dict())
    check_argv: tuple[str, ...] = (
        sys.executable,
        "-m",
        "tools.project_state.cli",
        "check",
        "--repo",
        str(repo),
        "--tree",
        candidate,
    )
    if max_findings is not None:
        check_argv = (*check_argv, "--max-findings", str(max_findings))
    return ValidationObservation(result, check_argv)


def materialize_current_candidate(target: Path) -> ValidationObservation:
    with step_context("Materialize exact working candidate as an immutable Git tree"):
        run_command(
            (
                "git",
                "clone",
                "--no-hardlinks",
                str(PROJECT_ROOT),
                str(target),
            ),
            step_title="Clone repository baseline and Git object history",
            attach_success=True,
        )
        manifest = build_git_source_manifest(PROJECT_ROOT)
        expected_paths = {entry.path for entry in manifest.document.files}
        tracked_result = run_git(target, "ls-files", "-z")
        if tracked_result.returncode != 0:
            raise RuntimeError("cannot list materialized baseline paths")
        tracked = tracked_result.stdout.decode("utf-8", "strict").split("\0")
        for relative in tracked:
            path = target / relative
            if (
                relative
                and relative not in expected_paths
                and (path.exists() or path.is_symlink())
            ):
                path.unlink()
        for entry in manifest.document.files:
            source = PROJECT_ROOT / entry.path
            destination = target / entry.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                destination.unlink()
            if entry.kind == "symlink":
                os.symlink(os.readlink(source), destination)
            else:
                shutil.copy2(source, destination)
        _git_text(target, "config", "user.name", "Flare Canonical Candidate Test")
        _git_text(
            target,
            "config",
            "user.email",
            "canonical-candidate@flare.invalid",
        )
        _git_text(target, "add", "-A")
        _git_text(
            target,
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "test: materialize exact candidate",
        )
        candidate = _git_text(target, "rev-parse", "HEAD")
        materialized = build_git_source_manifest(target)
        attach_json(
            "materialized candidate source identity",
            {
                "candidate_commit": candidate,
                "entry_count": len(materialized.document.files),
                "source_manifest_sha256": materialized.sha256,
            },
        )
        if materialized.sha256 != manifest.sha256:
            raise RuntimeError(
                "materialized candidate source identity differs from working candidate"
            )
    return observe_candidate_tree(target, candidate)


class RepositoryFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        with step_context("Initialize isolated coordination repository"):
            self.root.mkdir(parents=True)
            self.git("init", "-q", "-b", "coordination")
            self.git("config", "user.name", "Flare Test")
            self.git("config", "user.email", "flare-test@example.invalid")
            self._write_authorities()
            self.source_commit = self.commit_all("test: add authority sources")
            self.state = self.base_state(self.source_commit)
            state_raw = json_bytes(self.state)
            self.write(STATE_PATH, state_raw)
            self.write(PROJECTION_PATH, self.projection_for(state_raw))
            self.parent = self.commit_all("test: add accepted coordination state")
            attach_json(
                "fixture commit identities",
                {
                    "accepted_coordination_parent": self.parent,
                    "accepted_source_commit": self.source_commit,
                },
            )

    def __repr__(self) -> str:
        return f"RepositoryFixture(root={self.root})"

    def git(
        self,
        *args: str,
        evidence_step: str | None = None,
        attach_success: bool = False,
    ) -> str:
        return _git_text(
            self.root,
            *args,
            evidence_step=evidence_step,
            attach_success=attach_success,
        )

    def write(self, relative: str, content: str | bytes) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")

    def commit_all(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def commit_paths(self, message: str, *paths: str) -> str:
        self.git("add", "--", *paths)
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def remove_and_commit(self, relative: str, message: str) -> str:
        self.git("rm", "-q", "--", relative)
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def copy_state(self) -> dict[str, JSONValue]:
        copied: dict[str, JSONValue] = copy.deepcopy(self.state)
        return copied

    def schema_bytes(self) -> bytes:
        return (self.root / SCHEMA_PATH).read_bytes()

    def tree(self, revision: str) -> GitTree:
        tree = GitTree.resolve(self.root, revision)
        if tree is None:
            raise RuntimeError(f"revision does not resolve to a commit: {revision}")
        return tree

    def projection_for(self, raw: bytes) -> bytes:
        decoded = decode_state(raw, self.schema_bytes())
        if decoded.state is None:
            return b"invalid candidate has no generated projection\n"
        return render_projection(decoded.state)

    def candidate_commit(
        self,
        state: dict[str, JSONValue] | None = None,
        *,
        raw: bytes | None = None,
        projection: bytes | None = None,
    ) -> str:
        candidate = self.state if state is None else state
        state_raw = json_bytes(candidate) if raw is None else raw
        candidate_projection = (
            self.projection_for(state_raw) if projection is None else projection
        )
        self.write(STATE_PATH, state_raw)
        self.write(PROJECTION_PATH, candidate_projection)
        return self.commit_paths(
            "test: add coordination candidate",
            STATE_PATH,
            PROJECTION_PATH,
        )

    def validate(
        self,
        state: dict[str, JSONValue] | None = None,
        *,
        raw: bytes | None = None,
        projection: bytes | None = None,
        max_findings: int | None = None,
    ) -> ValidationObservation:
        with step_context("Build candidate coordination tree"):
            candidate = self.candidate_commit(state, raw=raw, projection=projection)
            paths = self.git(
                "ls-tree",
                "-r",
                "--name-only",
                candidate,
                evidence_step="List files in immutable candidate",
                attach_success=True,
            ).splitlines()
            tree = "\n".join(
                (
                    f"candidate {candidate}",
                    f"files: {len(paths)}",
                    *(f"├── {path}" for path in paths),
                )
            )
            attach_text("candidate tree", tree)
        return self.observe_candidate(candidate, max_findings)

    def observe_candidate(
        self,
        candidate: str,
        max_findings: int | None = None,
    ) -> ValidationObservation:
        return observe_candidate_tree(self.root, candidate, max_findings)

    def add_artifact(
        self,
        artifact_id: str,
        *,
        content: bytes = b"artifact\n",
        state_sha: str | None = None,
        manifest_sha: str | None = None,
        source_git_commit: str | None = None,
        suffix: str = "",
    ) -> dict[str, JSONValue]:
        artifact_ref = f"artifacts/{artifact_id}{suffix}.bin"
        manifest_ref = f"artifacts/{artifact_id}{suffix}.manifest.json"
        actual_sha = hashlib.sha256(content).hexdigest()
        declared_state_sha = state_sha or actual_sha
        kind = "source" if source_git_commit else "evidence"
        manifest: dict[str, JSONValue] = {
            "artifact_id": artifact_id,
            "artifact_ref": artifact_ref,
            "kind": kind,
            "sha256": manifest_sha or declared_state_sha,
        }
        if source_git_commit is not None:
            manifest["source_git_commit"] = source_git_commit
        self.write(artifact_ref, content)
        self.write(manifest_ref, json_bytes(manifest))
        self.commit_all(f"test: add artifact {artifact_id}{suffix}")
        return {
            "artifact_id": artifact_id,
            "kind": kind,
            "manifest_ref": manifest_ref,
            "sha256": declared_state_sha,
        }

    def add_authority_symlink(self) -> str:
        relative = "docs/symlink.md"
        link = self.root / relative
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to("onboarding/START-HERE.md")
        self.commit_all("test: add authority symlink")
        return relative

    def _write_authorities(self) -> None:
        fixtures = (
            (PRODUCTION_GATE_REF, "production_gate.md"),
            (PRODUCT_PHASE_REF, "product_phase.md"),
            (ENFORCEMENT_MATRIX_REF, "enforcement_matrix.md"),
            (ROLE_REGISTRY_REF, "role_registry.toml"),
            (ASSIGNMENT_REF, "integrator_assignment.json"),
            (CHANGE_REF, "change_contract.md"),
            ("docs/decisions/open.md", "open_decision.md"),
            ("docs/blockers/open.md", "open_blocker.md"),
        )
        for reference, fixture in fixtures:
            self.write(reference, (CORPUS / fixture).read_bytes())
        self.write(SCHEMA_PATH, (PROJECT_ROOT / SCHEMA_PATH).read_bytes())

    @staticmethod
    def base_state(source_commit: str) -> dict[str, JSONValue]:
        state = json_object(
            parse_strict_json((CORPUS / "state.template.json").read_bytes()),
            "state fixture",
        )
        baseline = json_object(state.get("accepted_source_baseline"), "source baseline")
        baseline["git_commit"] = source_commit
        return state
