import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, TypedDict

import typer
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from tools.project_state.json_codec import canonical_json_bytes, parse_strict_json
from tools.project_state.model import JSONValue
from tools.quality.source_manifest import build_directory_source_manifest
from tools.quality.tests.project_state.publication_scenarios import (
    PUBLICATION_SCENARIOS,
)
from tools.quality.tests.project_state.reporting import (
    CHANGE_CONTRACT_URL,
    MAX_ATTACHMENT_BYTES,
)
from tools.quality.tests.project_state.review_scenarios import REVIEW_SCENARIOS
from tools.quality.tests.project_state.runtime_evidence import (
    RuntimeAudit,
    RuntimeEvidenceError,
    audit_runtime_evidence,
)
from tools.quality.tests.project_state.scenario_catalog import VALIDATION_SCENARIOS

type ModelTuple[T] = Annotated[tuple[T, ...], Field(strict=False)]

_ACCEPTED_TEXTUAL_MEDIA_TYPES = frozenset({"application/json", "text/plain"})
_FORBIDDEN_SECRET_CANARY = "flare-closure-secret-canary"


class AllureModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)


class Label(AllureModel):
    name: StrictStr
    value: StrictStr


class Attachment(AllureModel):
    name: StrictStr
    source: StrictStr
    type: StrictStr


class Step(AllureModel):
    name: StrictStr
    steps: ModelTuple[Step] = ()
    attachments: ModelTuple[Attachment] = ()


class Parameter(AllureModel):
    name: StrictStr
    value: StrictStr


class Link(AllureModel):
    name: StrictStr
    url: StrictStr
    type: StrictStr


class Executable(AllureModel):
    name: StrictStr
    status: StrictStr = ""
    labels: ModelTuple[Label] = ()
    steps: ModelTuple[Step] = ()
    attachments: ModelTuple[Attachment] = ()
    parameters: ModelTuple[Parameter] = ()
    links: ModelTuple[Link] = ()


class Container(AllureModel):
    befores: ModelTuple[Executable] = ()
    afters: ModelTuple[Executable] = ()


class CommandOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    duration_ms: int
    exit_code: int
    stdout: StrictStr = ""
    stderr: StrictStr = ""


class AuditSummary(TypedDict):
    result_files: int
    container_files: int
    scenario_ids: list[str]
    step_count: int
    fixture_count: int
    attachment_count: int
    largest_attachment_bytes: int
    environment_ids: list[str]
    tagged_results: int
    linked_results: int
    concise_parameters: int
    candidate_listing_steps: int
    finding_evidence_steps: int
    public_cli_reproductions: int
    pure_model_evidence_steps: int
    scenario_variants: int
    configured_python: str
    observed_python: str
    observed_python_implementation: str
    pytest_version: str
    allure_pytest_version: str
    pytest_xdist_version: str
    configured_workers: int
    observed_workers: list[str]
    configured_distribution: str
    observed_execution: str
    source_manifest_sha256: str
    redacted_command_outputs: int
    truncated_command_outputs: int
    textual_attachments_scanned: int
    project_id: str
    baseline_commit: str
    active_change_ids: list[str]


class AllureAuditError(RuntimeError):
    pass


def _flatten(roots: tuple[Step, ...]) -> list[Step]:
    flattened: list[Step] = []
    pending = list(reversed(roots))
    while pending:
        step = pending.pop()
        flattened.append(step)
        pending.extend(reversed(step.steps))
    return flattened


def _labels(result: Executable, name: str) -> tuple[str, ...]:
    return tuple(label.value for label in result.labels if label.name == name)


def _expected_titles() -> set[str]:
    return (
        {scenario.pytest_id for scenario in VALIDATION_SCENARIOS}
        | {scenario.pytest_id for scenario in PUBLICATION_SCENARIOS}
        | {scenario.pytest_id for scenario in REVIEW_SCENARIOS}
    )


_REQUIRED_LABEL_NAMES = (
    "epic",
    "feature",
    "story",
    "parentSuite",
    "suite",
    "subSuite",
    "tag",
    "test_environment",
)
_REQUIRED_ATTACHMENT_NAMES = (
    "bounded validation result",
    "bounded race results",
    "candidate tree",
    "command",
    "command output",
    "publication evidence",
    "review verification input",
    "review verification output",
)
_REPRESENTATIVE_STEPS = {
    "A1-N28": {
        "Race two publications against one immutable CAS preimage",
        "Verify race publication outcomes",
        "Verify published race winner identity",
    },
    "A1-N30": {
        "Observe reference exists only in the working tree",
        "Reproduce result through the public project-state CLI",
    },
    "A1-N31": {"Independently reject a forged review target ID"},
    "A1-N32": {"Independently reject the wrong responding reviewer role"},
    "A1-C01": {"Move candidate ref after its state bytes are read"},
    "A1-C07": {
        "Materialize exact working candidate as an immutable Git tree",
        "Validate exact candidate tree",
    },
    "A1-C09": {
        "Produce oversized output containing a synthetic secret canary",
        "Verify complete command evidence safety and diagnostic value",
        "Verify failed-command evidence uses only safe diagnostics",
        "Verify the complete supported secret grammar",
    },
}


@dataclass(slots=True)
class _AllureAudit:
    results_dir: Path
    runtime: RuntimeAudit
    results: tuple[Executable, ...]
    containers: tuple[Container, ...]
    observed: set[str] = field(default_factory=set)
    result_steps: list[Step] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    environments: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    titled_fixtures: tuple[Executable, ...] = ()
    candidate_listing_steps: int = 0
    finding_evidence_steps: int = 0
    public_cli_reproductions: int = 0
    pure_model_evidence_steps: int = 0
    redacted_command_outputs: int = 0
    truncated_command_outputs: int = 0
    textual_attachments_scanned: int = 0
    largest_attachment_bytes: int = 0

    @property
    def fixtures(self) -> tuple[Executable, ...]:
        return tuple(
            fixture
            for container in self.containers
            for fixture in (*container.befores, *container.afters)
        )

    def run(self) -> AuditSummary:
        for result in self.results:
            self._audit_result(result)
        self._audit_fixtures()
        self._audit_inventory()
        self._audit_attachment_ownership()
        for attachment in self.attachments:
            self._audit_textual_attachment(attachment)
        if self.redacted_command_outputs < 1 or self.truncated_command_outputs < 1:
            self.errors.append(
                "command redaction/truncation policy lacks observed evidence"
            )
        if self.environments != {"isolated-git", "pure-model"}:
            self.errors.append(
                f"unexpected test environments: {sorted(self.environments)}"
            )
        if self.errors:
            raise AllureAuditError("; ".join(self.errors))
        return self._summary()

    def _audit_result(self, result: Executable) -> None:
        scenario_ids = _labels(result, "scenario_id")
        scenario_id = scenario_ids[0] if len(scenario_ids) == 1 else ""
        self.observed.update(scenario_ids)
        self._audit_result_identity(result, scenario_ids, scenario_id)
        self.attachments.extend(result.attachments)
        steps = _flatten(result.steps)
        self._audit_steps(result, scenario_id, steps)
        self.result_steps.extend(steps)
        self.attachments.extend(
            attachment for step in steps for attachment in step.attachments
        )

    def _audit_result_identity(
        self,
        result: Executable,
        scenario_ids: tuple[str, ...],
        scenario_id: str,
    ) -> None:
        if result.status != "passed":
            self.errors.append(f"non-passing result: {result.name}={result.status}")
        if len(scenario_ids) != 1 or not result.name.startswith(f"[{scenario_id}]"):
            self.errors.append(f"invalid scenario identity/title: {result.name}")
        if not result.name.strip() or not result.steps:
            self.errors.append(f"empty title or steps: {result.name}")
        self.errors.extend(
            f"scenario lacks {label}: {result.name}"
            for label in _REQUIRED_LABEL_NAMES
            if not _labels(result, label)
        )
        if _labels(result, "parentSuite") != ("Flare contract verification",):
            self.errors.append(f"unexpected parent suite: {result.name}")
        if _labels(result, "suite") != ("A.1 Coordination State",):
            self.errors.append(f"unexpected suite: {result.name}")
        if _labels(result, "subSuite") != _labels(result, "story"):
            self.errors.append(f"sub-suite and story diverge: {result.name}")
        self.environments.update(_labels(result, "test_environment"))
        if not {"a1", "contract"} <= set(_labels(result, "tag")):
            self.errors.append(f"scenario lacks navigation tags: {result.name}")
        if (
            len(result.parameters) != 1
            or result.parameters[0].name != "scenario"
            or result.parameters[0].value != result.name
            or "Scenario(" in result.parameters[0].value
            or "0x" in result.parameters[0].value
        ):
            self.errors.append(
                f"decorator title and parameter ID diverge: {result.name}"
            )
        if len(result.links) != 1 or result.links[0].url != CHANGE_CONTRACT_URL:
            self.errors.append(f"stable Change contract link is missing: {result.name}")
        if result.attachments:
            self.errors.append(f"test-root attachments are forbidden: {result.name}")

    def _audit_steps(
        self,
        result: Executable,
        scenario_id: str,
        steps: list[Step],
    ) -> None:
        expected_steps = _REPRESENTATIVE_STEPS.get(scenario_id, set())
        if not expected_steps <= {step.name for step in steps}:
            self.errors.append(
                f"representative nested steps are missing: {result.name}"
            )
        environment = _labels(result, "test_environment")
        for current in steps:
            descendants = _flatten(current.steps)
            if current.name == "Build candidate coordination tree":
                self._audit_candidate_listing(result, descendants)
            if current.name == "Reproduce result through the public project-state CLI":
                self.public_cli_reproductions += 1
            if current.name.startswith("Verify finding "):
                self._audit_finding_evidence(current, descendants, environment)

    def _audit_candidate_listing(
        self,
        result: Executable,
        descendants: list[Step],
    ) -> None:
        listings = tuple(
            child
            for child in descendants
            if child.name == "List files in immutable candidate"
        )
        listing_names = {
            attachment.name for child in listings for attachment in child.attachments
        }
        if len(listings) != 1 or not {"command", "command output"} <= listing_names:
            self.errors.append(f"candidate listing evidence is missing: {result.name}")
        self.candidate_listing_steps += len(listings)

    def _audit_finding_evidence(
        self,
        current: Step,
        descendants: list[Step],
        environment: tuple[str, ...],
    ) -> None:
        owned_names = {
            attachment.name
            for owner in (current, *descendants)
            for attachment in owner.attachments
        }
        has_cli = {"command", "command output"} <= owned_names
        has_model = {
            "review verification input",
            "review verification output",
        } <= owned_names
        expected_evidence = has_cli if environment == ("isolated-git",) else has_model
        if not expected_evidence:
            self.errors.append(f"finding step lacks owned evidence: {current.name}")
        self.finding_evidence_steps += 1
        self.pure_model_evidence_steps += int(has_model)

    def _audit_fixtures(self) -> None:
        self.titled_fixtures = tuple(
            fixture
            for fixture in self.fixtures
            if fixture.name == "Create isolated coordination Git repository"
        )
        if not self.titled_fixtures or any(
            not fixture.steps for fixture in self.titled_fixtures
        ):
            self.errors.append("titled repository fixture with setup steps is missing")
        for fixture in self.fixtures:
            if fixture.attachments:
                self.errors.append(
                    f"fixture-root attachments are forbidden: {fixture.name}"
                )
            self.attachments.extend(fixture.attachments)
            self.attachments.extend(
                attachment
                for step in _flatten(fixture.steps)
                for attachment in step.attachments
            )

    def _audit_inventory(self) -> None:
        expected = {f"A1-N{index:02d}" for index in range(1, 33)}
        missing = sorted(expected - self.observed)
        if missing:
            self.errors.append(f"missing normative scenario IDs: {', '.join(missing)}")
        expected_titles = _expected_titles()
        observed_titles = {result.name for result in self.results}
        if (
            len(self.results) != len(expected_titles)
            or observed_titles != expected_titles
        ):
            self.errors.append(
                "scenario variants differ: "
                f"results={len(self.results)}, "
                f"missing={sorted(expected_titles - observed_titles)}, "
                f"unexpected={sorted(observed_titles - expected_titles)}"
            )
        names = {attachment.name for attachment in self.attachments}
        self.errors.extend(
            f"representative attachment is missing: {required}"
            for required in _REQUIRED_ATTACHMENT_NAMES
            if required not in names
        )

    def _audit_attachment_ownership(self) -> None:
        paths = tuple(sorted(self.results_dir.glob("*-attachment.*")))
        referenced = {attachment.source for attachment in self.attachments}
        if referenced != {path.name for path in paths}:
            self.errors.append("attachment files and step-owned references differ")
        self.largest_attachment_bytes = max(
            (path.stat().st_size for path in paths),
            default=0,
        )
        if self.largest_attachment_bytes > MAX_ATTACHMENT_BYTES:
            self.errors.append(
                f"attachment exceeds {MAX_ATTACHMENT_BYTES} bytes: "
                f"{self.largest_attachment_bytes}"
            )
        names = {attachment.name for attachment in self.attachments}
        if {"stdout", "stderr", "log"} & names:
            self.errors.append("automatic global capture attachment detected")
        owned_steps = [*self.result_steps]
        for fixture in self.fixtures:
            owned_steps.extend(_flatten(fixture.steps))
        for owner in owned_steps:
            self._audit_command_pair(owner)

    def _audit_command_pair(self, owner: Step) -> None:
        names = [attachment.name for attachment in owner.attachments]
        has_command = "command" in names
        has_output = "command output" in names
        if has_command != has_output:
            self.errors.append(f"command evidence is not paired: {owner.name}")
        if names.count("command") > 1 or names.count("command output") > 1:
            self.errors.append(f"command evidence is duplicated: {owner.name}")

    def _audit_textual_attachment(self, attachment: Attachment) -> None:
        path = self.results_dir / attachment.source
        if not path.is_file():
            self.errors.append(f"attachment source is missing: {attachment.source}")
            return
        if attachment.type not in _ACCEPTED_TEXTUAL_MEDIA_TYPES:
            self.errors.append(
                "unsupported attachment media type: "
                f"{attachment.type} ({attachment.source})"
            )
            return
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            self.errors.append(f"textual attachment is not UTF-8: {attachment.source}")
            return
        self.textual_attachments_scanned += 1
        if _FORBIDDEN_SECRET_CANARY in text:
            self.errors.append(
                "synthetic secret canary survived durable textual evidence: "
                f"{attachment.source}"
            )
        self._audit_attachment_content(attachment, path, text)

    def _audit_attachment_content(
        self,
        attachment: Attachment,
        path: Path,
        text: str,
    ) -> None:
        if attachment.name == "candidate tree" and not (
            text.startswith("candidate ") and "\nfiles: " in text
        ):
            self.errors.append("candidate tree attachment is not readable")
        if attachment.name == "command" and (
            not text.strip() or text.startswith("$ ") or "\n" in text
        ):
            self.errors.append("command attachment is not directly copyable")
        if attachment.name != "command output":
            return
        output = CommandOutput.model_validate_json(path.read_bytes())
        if not output.stdout and not output.stderr:
            self.errors.append("command output attachment has no observed stream")
        rendered_output = f"{output.stdout}\n{output.stderr}"
        self.redacted_command_outputs += int(
            "REDACTED_SUPPORTED_SECRET" in rendered_output
        )
        self.truncated_command_outputs += int("[TRUNCATED " in rendered_output)

    def _summary(self) -> AuditSummary:
        return {
            "allure_pytest_version": self.runtime.allure_pytest_version,
            "attachment_count": len(self.attachments),
            "candidate_listing_steps": self.candidate_listing_steps,
            "container_files": len(self.containers),
            "concise_parameters": len(self.results),
            "configured_distribution": self.runtime.configured_distribution,
            "configured_python": self.runtime.configured_python,
            "configured_workers": self.runtime.configured_workers,
            "environment_ids": sorted(self.environments),
            "fixture_count": len(self.titled_fixtures),
            "finding_evidence_steps": self.finding_evidence_steps,
            "largest_attachment_bytes": self.largest_attachment_bytes,
            "linked_results": len(self.results),
            "observed_execution": self.runtime.observed_execution,
            "observed_python": self.runtime.observed_python,
            "observed_python_implementation": self.runtime.observed_implementation,
            "observed_workers": list(self.runtime.observed_workers),
            "public_cli_reproductions": self.public_cli_reproductions,
            "pure_model_evidence_steps": self.pure_model_evidence_steps,
            "pytest_version": self.runtime.pytest_version,
            "pytest_xdist_version": self.runtime.pytest_xdist_version,
            "result_files": len(self.results),
            "scenario_variants": len(_expected_titles()),
            "scenario_ids": sorted(self.observed),
            "source_manifest_sha256": self.runtime.source_manifest_sha256,
            "step_count": len(self.result_steps),
            "tagged_results": len(self.results),
            "redacted_command_outputs": self.redacted_command_outputs,
            "truncated_command_outputs": self.truncated_command_outputs,
            "textual_attachments_scanned": self.textual_attachments_scanned,
            "project_id": self.runtime.project_id,
            "baseline_commit": self.runtime.baseline_commit,
            "active_change_ids": list(self.runtime.active_change_ids),
        }


def audit_allure_results(results_dir: Path) -> AuditSummary:
    runtime = audit_runtime_evidence(results_dir, Path.cwd())
    results = tuple(
        Executable.model_validate_json(path.read_bytes())
        for path in sorted(results_dir.glob("*-result.json"))
    )
    containers = tuple(
        Container.model_validate_json(path.read_bytes())
        for path in sorted(results_dir.glob("*-container.json"))
    )
    return _AllureAudit(results_dir, runtime, results, containers).run()


def audit_adversarial_proofs(results_dir: Path) -> dict[str, str]:
    specifications: tuple[
        tuple[str, Callable[[Path], None], str],
        ...,
    ] = (
        (
            "stale_source_manifest",
            _replace_source_manifest,
            "source identity differs",
        ),
        (
            "runtime_version_mismatch",
            _mismatch_configured_python,
            "configured Python differs",
        ),
        (
            "root_attachment",
            _add_root_attachment,
            "test-root attachments are forbidden",
        ),
        (
            "oversized_attachment",
            _oversize_attachment,
            "attachment exceeds",
        ),
        (
            "missing_worker_observation",
            _remove_worker_observation,
            "configured workers differ",
        ),
        (
            "neutral_text_canary",
            _inject_neutral_text_canary,
            "synthetic secret canary survived durable textual evidence",
        ),
        (
            "json_canary",
            _inject_json_canary,
            "synthetic secret canary survived durable textual evidence",
        ),
        (
            "unsupported_attachment_media_type",
            _relabel_text_as_binary,
            "unsupported attachment media type",
        ),
    )
    proofs: dict[str, str] = {}
    for name, mutation, expected in specifications:
        proofs[name] = _expect_rejection(results_dir, mutation, expected)
    return proofs


def _expect_rejection(
    results_dir: Path,
    mutation: Callable[[Path], None],
    expected: str,
) -> str:
    with tempfile.TemporaryDirectory(prefix="flare-allure-red-") as directory:
        attacked = Path(directory) / "results"
        shutil.copytree(results_dir, attacked)
        mutation(attacked)
        try:
            audit_allure_results(attacked)
        except (AllureAuditError, RuntimeEvidenceError) as error:
            detail = str(error)
            if expected not in detail:
                raise AllureAuditError(
                    f"intentional RED produced the wrong signal: {detail}"
                ) from error
            return expected
    raise AllureAuditError(f"intentional RED was accepted: {expected}")


def _replace_source_manifest(results_dir: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="flare-wrong-source-") as directory:
        wrong_source = Path(directory)
        (wrong_source / "wrong.txt").write_text("wrong candidate\n", encoding="utf-8")
        manifest = build_directory_source_manifest(wrong_source)
    (results_dir / "source-manifest.json").write_bytes(manifest.encoded)


def _mismatch_configured_python(results_dir: Path) -> None:
    path = results_dir / "environment.properties"
    lines = path.read_text(encoding="utf-8").splitlines()
    replaced = tuple(
        "Python.version.configured=0.0.0"
        if line.startswith("Python.version.configured=")
        else line
        for line in lines
    )
    path.write_text(f"{'\n'.join(replaced)}\n", encoding="utf-8")


def _add_root_attachment(results_dir: Path) -> None:
    result_path = next(iter(sorted(results_dir.glob("*-result.json"))), None)
    attachment_path = next(iter(sorted(results_dir.glob("*-attachment.*"))), None)
    if result_path is None or attachment_path is None:
        raise AllureAuditError("cannot prepare root-attachment intentional RED")
    value = parse_strict_json(result_path.read_bytes())
    if not isinstance(value, dict):
        raise AllureAuditError("Allure result is not a JSON object")
    attachment: dict[str, JSONValue] = {
        "name": "forbidden root evidence",
        "source": attachment_path.name,
        "type": "text/plain",
    }
    value["attachments"] = [attachment]
    result_path.write_bytes(canonical_json_bytes(value))


def _oversize_attachment(results_dir: Path) -> None:
    path = next(iter(sorted(results_dir.glob("*-attachment.txt"))), None)
    if path is None:
        raise AllureAuditError("cannot prepare oversized-attachment intentional RED")
    path.write_bytes(b"x" * (MAX_ATTACHMENT_BYTES + 1))


def _remove_worker_observation(results_dir: Path) -> None:
    path = next(iter(sorted(results_dir.glob("runtime-observation-gw*.json"))), None)
    if path is None:
        raise AllureAuditError("cannot prepare missing-worker intentional RED")
    path.unlink()


def _inject_neutral_text_canary(results_dir: Path) -> None:
    _, attachment = _find_result_attachment(
        results_dir,
        media_type="text/plain",
        excluded_names=frozenset({"command", "command output"}),
    )
    path = results_dir / attachment.source
    existing = path.read_text(encoding="utf-8")
    path.write_text(
        f"{existing}\n{_FORBIDDEN_SECRET_CANARY}\n",
        encoding="utf-8",
    )


def _inject_json_canary(results_dir: Path) -> None:
    _, attachment = _find_result_attachment(
        results_dir,
        media_type="application/json",
        excluded_names=frozenset({"command output"}),
    )
    path = results_dir / attachment.source
    path.write_bytes(
        canonical_json_bytes({"synthetic_secret": _FORBIDDEN_SECRET_CANARY})
    )


def _relabel_text_as_binary(results_dir: Path) -> None:
    result_path, attachment = _find_result_attachment(
        results_dir,
        media_type="text/plain",
        excluded_names=frozenset({"command", "command output"}),
    )
    value = parse_strict_json(result_path.read_bytes())
    if not _replace_attachment_media_type(value, attachment.source):
        raise AllureAuditError("cannot relabel textual attachment intentional RED")
    result_path.write_bytes(canonical_json_bytes(value))


def _find_result_attachment(
    results_dir: Path,
    *,
    media_type: str,
    excluded_names: frozenset[str],
) -> tuple[Path, Attachment]:
    for result_path in sorted(results_dir.glob("*-result.json")):
        result = Executable.model_validate_json(result_path.read_bytes())
        for step in _flatten(result.steps):
            for attachment in step.attachments:
                if (
                    attachment.type == media_type
                    and attachment.name not in excluded_names
                ):
                    return result_path, attachment
    raise AllureAuditError(f"cannot find {media_type} attachment for intentional RED")


def _replace_attachment_media_type(value: JSONValue, source: str) -> bool:
    if isinstance(value, dict):
        if value.get("source") == source and value.get("type") == "text/plain":
            value["type"] = "application/octet-stream"
            return True
        return any(
            _replace_attachment_media_type(child, source) for child in value.values()
        )
    if isinstance(value, list):
        return any(_replace_attachment_media_type(child, source) for child in value)
    return False


def main(
    results_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
) -> None:
    typer.echo(
        json.dumps(
            {
                "audit": audit_allure_results(results_dir),
                "intentional_red": audit_adversarial_proofs(results_dir),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    typer.run(main)
