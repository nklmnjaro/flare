import json
import shutil
import tempfile
from collections.abc import Callable
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
    expected = {f"A1-N{index:02d}" for index in range(1, 33)}
    expected_titles = _expected_titles()
    observed: set[str] = set()
    result_steps: list[Step] = []
    attachments: list[Attachment] = []
    environments: set[str] = set()
    errors: list[str] = []
    candidate_listing_steps = 0
    finding_evidence_steps = 0
    public_cli_reproductions = 0
    pure_model_evidence_steps = 0
    redacted_command_outputs = 0
    truncated_command_outputs = 0
    textual_attachments_scanned = 0

    for result in results:
        scenario_ids = _labels(result, "scenario_id")
        scenario_id = scenario_ids[0] if len(scenario_ids) == 1 else ""
        observed.update(scenario_ids)
        if result.status != "passed":
            errors.append(f"non-passing result: {result.name}={result.status}")
        if len(scenario_ids) != 1 or not result.name.startswith(f"[{scenario_ids[0]}]"):
            errors.append(f"invalid scenario identity/title: {result.name}")
        if not result.name.strip() or not result.steps:
            errors.append(f"empty title or steps: {result.name}")
        errors.extend(
            f"scenario lacks {label}: {result.name}"
            for label in (
                "epic",
                "feature",
                "story",
                "parentSuite",
                "suite",
                "subSuite",
                "tag",
                "test_environment",
            )
            if not _labels(result, label)
        )
        if _labels(result, "parentSuite") != ("Flare contract verification",):
            errors.append(f"unexpected parent suite: {result.name}")
        if _labels(result, "suite") != ("A.1 Coordination State",):
            errors.append(f"unexpected suite: {result.name}")
        if _labels(result, "subSuite") != _labels(result, "story"):
            errors.append(f"sub-suite and story diverge: {result.name}")
        environments.update(_labels(result, "test_environment"))
        tags = set(_labels(result, "tag"))
        if not {"a1", "contract"} <= tags:
            errors.append(f"scenario lacks navigation tags: {result.name}")
        if (
            len(result.parameters) != 1
            or result.parameters[0].name != "scenario"
            or result.parameters[0].value != result.name
            or "Scenario(" in result.parameters[0].value
            or "0x" in result.parameters[0].value
        ):
            errors.append(f"decorator title and parameter ID diverge: {result.name}")
        if len(result.links) != 1 or result.links[0].url != CHANGE_CONTRACT_URL:
            errors.append(f"stable Change contract link is missing: {result.name}")
        if result.attachments:
            errors.append(f"test-root attachments are forbidden: {result.name}")
        attachments.extend(result.attachments)
        steps = _flatten(result.steps)
        step_names = {step.name for step in steps}
        representative_steps = {
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
        }.get(scenario_id, set())
        if not representative_steps <= step_names:
            errors.append(f"representative nested steps are missing: {result.name}")
        environment = _labels(result, "test_environment")
        for current in steps:
            descendants = _flatten(current.steps)
            if current.name == "Build candidate coordination tree":
                listings = tuple(
                    child
                    for child in descendants
                    if child.name == "List files in immutable candidate"
                )
                listing_names = {
                    attachment.name
                    for child in listings
                    for attachment in child.attachments
                }
                if (
                    len(listings) != 1
                    or not {"command", "command output"} <= listing_names
                ):
                    errors.append(
                        f"candidate listing evidence is missing: {result.name}"
                    )
                candidate_listing_steps += len(listings)
            if current.name == "Reproduce result through the public project-state CLI":
                public_cli_reproductions += 1
            if not current.name.startswith("Verify finding "):
                continue
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
            expected_evidence = (
                has_cli if environment == ("isolated-git",) else has_model
            )
            if not expected_evidence:
                errors.append(f"finding step lacks owned evidence: {current.name}")
            finding_evidence_steps += 1
            pure_model_evidence_steps += int(has_model)
        result_steps.extend(steps)
        attachments.extend(item for step in steps for item in step.attachments)

    fixtures = tuple(
        fixture
        for container in containers
        for fixture in (*container.befores, *container.afters)
    )
    titled = tuple(
        fixture
        for fixture in fixtures
        if fixture.name == "Create isolated coordination Git repository"
    )
    if not titled or any(not fixture.steps for fixture in titled):
        errors.append("titled repository fixture with setup steps is missing")
    for fixture in fixtures:
        if fixture.attachments:
            errors.append(f"fixture-root attachments are forbidden: {fixture.name}")
        attachments.extend(fixture.attachments)
        attachments.extend(
            item for step in _flatten(fixture.steps) for item in step.attachments
        )

    missing = sorted(expected - observed)
    if missing:
        errors.append(f"missing normative scenario IDs: {', '.join(missing)}")
    observed_titles = {result.name for result in results}
    if len(results) != len(expected_titles) or observed_titles != expected_titles:
        errors.append(
            "scenario variants differ: "
            f"results={len(results)}, "
            f"missing={sorted(expected_titles - observed_titles)}, "
            f"unexpected={sorted(observed_titles - expected_titles)}"
        )
    names = {attachment.name for attachment in attachments}
    errors.extend(
        f"representative attachment is missing: {required}"
        for required in (
            "bounded validation result",
            "bounded race results",
            "candidate tree",
            "command",
            "command output",
            "publication evidence",
            "review verification input",
            "review verification output",
        )
        if required not in names
    )

    attachment_paths = tuple(sorted(results_dir.glob("*-attachment.*")))
    referenced = {attachment.source for attachment in attachments}
    if referenced != {path.name for path in attachment_paths}:
        errors.append("attachment files and step-owned references differ")
    largest = max((path.stat().st_size for path in attachment_paths), default=0)
    if largest > MAX_ATTACHMENT_BYTES:
        errors.append(f"attachment exceeds {MAX_ATTACHMENT_BYTES} bytes: {largest}")
    if {"stdout", "stderr", "log"} & names:
        errors.append("automatic global capture attachment detected")
    owned_steps = [*result_steps]
    for fixture in fixtures:
        owned_steps.extend(_flatten(fixture.steps))
    for owner in owned_steps:
        command_attachment_names = [attachment.name for attachment in owner.attachments]
        has_command = "command" in command_attachment_names
        has_output = "command output" in command_attachment_names
        if has_command != has_output:
            errors.append(f"command evidence is not paired: {owner.name}")
        if (
            command_attachment_names.count("command") > 1
            or command_attachment_names.count("command output") > 1
        ):
            errors.append(f"command evidence is duplicated: {owner.name}")

    for attachment in attachments:
        path = results_dir / attachment.source
        if not path.is_file():
            errors.append(f"attachment source is missing: {attachment.source}")
            continue
        if attachment.type not in _ACCEPTED_TEXTUAL_MEDIA_TYPES:
            errors.append(
                "unsupported attachment media type: "
                f"{attachment.type} ({attachment.source})"
            )
            continue
        try:
            textual_evidence = path.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            errors.append(f"textual attachment is not UTF-8: {attachment.source}")
            continue
        textual_attachments_scanned += 1
        if _FORBIDDEN_SECRET_CANARY in textual_evidence:
            errors.append(
                "synthetic secret canary survived durable textual evidence: "
                f"{attachment.source}"
            )
        if attachment.name == "candidate tree":
            candidate_tree = textual_evidence
            if not (
                candidate_tree.startswith("candidate ")
                and "\nfiles: " in candidate_tree
            ):
                errors.append("candidate tree attachment is not readable")
        if attachment.name == "command":
            command = textual_evidence
            if not command.strip() or command.startswith("$ ") or "\n" in command:
                errors.append("command attachment is not directly copyable")
        if attachment.name == "command output":
            output = CommandOutput.model_validate_json(path.read_bytes())
            if not output.stdout and not output.stderr:
                errors.append("command output attachment has no observed stream")
            rendered_output = f"{output.stdout}\n{output.stderr}"
            redacted_command_outputs += int(
                "REDACTED_SUPPORTED_SECRET" in rendered_output
            )
            truncated_command_outputs += int("[TRUNCATED " in rendered_output)
    if redacted_command_outputs < 1 or truncated_command_outputs < 1:
        errors.append("command redaction/truncation policy lacks observed evidence")
    if environments != {"isolated-git", "pure-model"}:
        errors.append(f"unexpected test environments: {sorted(environments)}")
    if errors:
        raise AllureAuditError("; ".join(errors))
    return {
        "allure_pytest_version": runtime.allure_pytest_version,
        "attachment_count": len(attachments),
        "candidate_listing_steps": candidate_listing_steps,
        "container_files": len(containers),
        "concise_parameters": len(results),
        "configured_distribution": runtime.configured_distribution,
        "configured_python": runtime.configured_python,
        "configured_workers": runtime.configured_workers,
        "environment_ids": sorted(environments),
        "fixture_count": len(titled),
        "finding_evidence_steps": finding_evidence_steps,
        "largest_attachment_bytes": largest,
        "linked_results": len(results),
        "observed_execution": runtime.observed_execution,
        "observed_python": runtime.observed_python,
        "observed_python_implementation": runtime.observed_implementation,
        "observed_workers": list(runtime.observed_workers),
        "public_cli_reproductions": public_cli_reproductions,
        "pure_model_evidence_steps": pure_model_evidence_steps,
        "pytest_version": runtime.pytest_version,
        "pytest_xdist_version": runtime.pytest_xdist_version,
        "result_files": len(results),
        "scenario_variants": len(expected_titles),
        "scenario_ids": sorted(observed),
        "source_manifest_sha256": runtime.source_manifest_sha256,
        "step_count": len(result_steps),
        "tagged_results": len(results),
        "redacted_command_outputs": redacted_command_outputs,
        "truncated_command_outputs": truncated_command_outputs,
        "textual_attachments_scanned": textual_attachments_scanned,
        "project_id": runtime.project_id,
        "baseline_commit": runtime.baseline_commit,
        "active_change_ids": list(runtime.active_change_ids),
    }


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
