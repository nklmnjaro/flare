import os
import platform
import sys
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from tools.project_state.json_codec import parse_strict_json
from tools.project_state.model import CoordinationState
from tools.quality.source_manifest import (
    SourceManifestError,
    build_git_source_manifest,
    parse_source_manifest,
)

ENVIRONMENT_FILE = "environment.properties"
SOURCE_MANIFEST_FILE = "source-manifest.json"
_OBSERVATION_PREFIX = "runtime-observation-"


class RuntimeObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    executor_id: StrictStr
    implementation: StrictStr
    python_version: StrictStr
    pytest_version: StrictStr
    allure_pytest_version: StrictStr
    pytest_xdist_version: StrictStr
    reported_worker_count: StrictInt | None


@dataclass(frozen=True, slots=True)
class RuntimeAudit:
    configured_python: str
    observed_implementation: str
    observed_python: str
    pytest_version: str
    allure_pytest_version: str
    pytest_xdist_version: str
    configured_workers: int
    observed_workers: tuple[str, ...]
    configured_distribution: str
    observed_execution: str
    source_manifest_sha256: str
    project_id: str
    baseline_commit: str
    active_change_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateProvenance:
    project_id: str
    baseline_commit: str
    active_change_ids: tuple[str, ...]


class RuntimeEvidenceError(RuntimeError):
    pass


def record_runtime_observation(results_dir: Path) -> None:
    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    executor_id = worker_id or "controller"
    reported_worker_count = _optional_positive_int(
        os.environ.get("PYTEST_XDIST_WORKER_COUNT")
    )
    observation = RuntimeObservation(
        executor_id=executor_id,
        implementation=sys.implementation.name,
        python_version=platform.python_version(),
        pytest_version=version("pytest"),
        allure_pytest_version=version("allure-pytest"),
        pytest_xdist_version=version("pytest-xdist"),
        reported_worker_count=reported_worker_count,
    )
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{_OBSERVATION_PREFIX}{executor_id}.json"
    path.write_text(f"{observation.model_dump_json(indent=2)}\n", encoding="utf-8")


def finalize_runtime_evidence(
    results_dir: Path,
    repo: Path,
    configured_workers: int,
    configured_distribution: str,
) -> RuntimeAudit:
    observations = _load_observations(results_dir)
    manifest = build_git_source_manifest(repo)
    provenance = _candidate_provenance(repo)
    configured_python = (repo / ".python-version").read_text(encoding="utf-8").strip()
    audit = _validate_runtime(
        observations,
        configured_python,
        configured_workers,
        configured_distribution,
        manifest.sha256,
        provenance,
    )
    (results_dir / SOURCE_MANIFEST_FILE).write_bytes(manifest.encoded)
    _write_environment(results_dir / ENVIRONMENT_FILE, audit)
    return audit


def audit_runtime_evidence(results_dir: Path, repo: Path) -> RuntimeAudit:
    properties = _read_environment(results_dir / ENVIRONMENT_FILE)
    observations = _load_observations(results_dir)
    try:
        manifest = parse_source_manifest(
            (results_dir / SOURCE_MANIFEST_FILE).read_bytes()
        )
    except (OSError, SourceManifestError, ValueError) as error:
        raise RuntimeEvidenceError(
            f"invalid source manifest evidence: {error}"
        ) from error
    current_manifest = build_git_source_manifest(repo)
    if manifest.sha256 != current_manifest.sha256:
        raise RuntimeEvidenceError(
            "Allure source identity differs from current candidate: "
            f"results={manifest.sha256}, current={current_manifest.sha256}"
        )
    configured_workers = _property_int(properties, "xdist.workers.configured")
    provenance = _candidate_provenance(repo)
    audit = _validate_runtime(
        observations,
        properties.get("Python.version.configured", ""),
        configured_workers,
        properties.get("xdist.distribution.configured", ""),
        manifest.sha256,
        provenance,
    )
    expected_properties = _environment_properties(audit)
    if properties != expected_properties:
        raise RuntimeEvidenceError(
            "environment.properties differs from runtime evidence"
        )
    return audit


def main(
    results_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    repo: Annotated[Path, typer.Option("--repo", file_okay=False)] = Path("."),
    configured_workers: Annotated[int, typer.Option("--configured-workers")] = 4,
    configured_distribution: Annotated[
        str, typer.Option("--configured-distribution")
    ] = "worksteal",
) -> None:
    try:
        audit = finalize_runtime_evidence(
            results_dir,
            repo,
            configured_workers,
            configured_distribution,
        )
    except (OSError, SourceManifestError, RuntimeEvidenceError, ValueError) as error:
        typer.echo(f"RUNTIME EVIDENCE INVALID: {error}", err=True)
        raise typer.Exit(1) from None
    typer.echo(
        f"configured_python={audit.configured_python} "
        f"observed_python={audit.observed_python} "
        f"observed_workers={','.join(audit.observed_workers)}"
    )


def _load_observations(results_dir: Path) -> tuple[RuntimeObservation, ...]:
    observations = tuple(
        RuntimeObservation.model_validate_json(path.read_bytes())
        for path in sorted(results_dir.glob(f"{_OBSERVATION_PREFIX}*.json"))
    )
    if not observations:
        raise RuntimeEvidenceError("pytest runtime observations are missing")
    return observations


def _validate_runtime(
    observations: tuple[RuntimeObservation, ...],
    configured_python: str,
    configured_workers: int,
    configured_distribution: str,
    source_manifest_sha256: str,
    provenance: CandidateProvenance,
) -> RuntimeAudit:
    errors: list[str] = []
    by_executor = {observation.executor_id: observation for observation in observations}
    if len(by_executor) != len(observations):
        errors.append("duplicate pytest executor observations")
    controller = by_executor.get("controller")
    if controller is None:
        errors.append("pytest controller observation is missing")
    implementations = {item.implementation for item in observations}
    python_versions = {item.python_version for item in observations}
    pytest_versions = {item.pytest_version for item in observations}
    allure_versions = {item.allure_pytest_version for item in observations}
    xdist_versions = {item.pytest_xdist_version for item in observations}
    workers = tuple(
        sorted(executor for executor in by_executor if executor != "controller")
    )
    if implementations != {"cpython"}:
        errors.append(f"unexpected Python implementations: {sorted(implementations)}")
    if python_versions != {configured_python}:
        errors.append(
            "configured Python differs from observed pytest runtime: "
            f"configured={configured_python}, observed={sorted(python_versions)}"
        )
    if (
        len(pytest_versions) != 1
        or len(allure_versions) != 1
        or len(xdist_versions) != 1
    ):
        errors.append("test package versions differ across pytest executors")
    if configured_workers < 1:
        errors.append(f"configured workers must be positive: {configured_workers}")
    if len(workers) != configured_workers:
        errors.append(
            "configured workers differ from observed pytest workers: "
            f"configured={configured_workers}, observed={workers}"
        )
    reported_counts = {
        item.reported_worker_count
        for item in observations
        if item.reported_worker_count is not None
    }
    if reported_counts != {configured_workers}:
        errors.append(
            "pytest-xdist reported worker count differs: "
            f"configured={configured_workers}, reported={sorted(reported_counts)}"
        )
    if not configured_distribution:
        errors.append("configured xdist distribution is empty")
    if errors:
        raise RuntimeEvidenceError("; ".join(errors))
    return RuntimeAudit(
        configured_python=configured_python,
        observed_implementation=_only(implementations, "implementation"),
        observed_python=_only(python_versions, "Python version"),
        pytest_version=_only(pytest_versions, "pytest version"),
        allure_pytest_version=_only(allure_versions, "allure-pytest version"),
        pytest_xdist_version=_only(xdist_versions, "pytest-xdist version"),
        configured_workers=configured_workers,
        observed_workers=workers,
        configured_distribution=configured_distribution,
        observed_execution="parallel" if workers else "sequential",
        source_manifest_sha256=source_manifest_sha256,
        project_id=provenance.project_id,
        baseline_commit=provenance.baseline_commit,
        active_change_ids=provenance.active_change_ids,
    )


def _environment_properties(audit: RuntimeAudit) -> dict[str, str]:
    return {
        "Candidate.source_manifest.sha256": audit.source_manifest_sha256,
        "Flare.active_changes": ",".join(audit.active_change_ids),
        "Flare.project": audit.project_id,
        "Git.baseline": audit.baseline_commit,
        "Python.implementation.observed": audit.observed_implementation,
        "Python.version.configured": audit.configured_python,
        "Python.version.observed": audit.observed_python,
        "allure-pytest.version.observed": audit.allure_pytest_version,
        "pytest-xdist.version.observed": audit.pytest_xdist_version,
        "pytest.version.observed": audit.pytest_version,
        "xdist.distribution.configured": audit.configured_distribution,
        "xdist.execution.observed": audit.observed_execution,
        "xdist.workers.configured": str(audit.configured_workers),
        "xdist.workers.observed": ",".join(audit.observed_workers),
    }


def _write_environment(path: Path, audit: RuntimeAudit) -> None:
    properties = _environment_properties(audit)
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in sorted(properties.items())),
        encoding="utf-8",
    )


def _read_environment(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RuntimeEvidenceError(f"cannot read {path.name}: {error}") from error
    properties: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or not key or key in properties:
            raise RuntimeEvidenceError(f"invalid environment property: {line!r}")
        properties[key] = value
    return properties


def _property_int(properties: dict[str, str], key: str) -> int:
    try:
        return int(properties[key])
    except (KeyError, ValueError) as error:
        raise RuntimeEvidenceError(
            f"invalid integer environment property: {key}"
        ) from error


def _optional_positive_int(value: str | None) -> int | None:
    if value is None:
        return None
    parsed = int(value)
    if parsed < 1:
        raise RuntimeEvidenceError(f"worker count must be positive: {parsed}")
    return parsed


def _only(values: set[str], description: str) -> str:
    if len(values) != 1:
        raise RuntimeEvidenceError(
            f"expected one observed {description}: {sorted(values)}"
        )
    return next(iter(values))


def _candidate_provenance(repo: Path) -> CandidateProvenance:
    value = parse_strict_json((repo / "docs/project/state.json").read_bytes())
    state = CoordinationState.model_validate(value)
    return CandidateProvenance(
        project_id=state.project_id,
        baseline_commit=state.accepted_source_baseline.git_commit,
        active_change_ids=tuple(change.change_id for change in state.active_changes),
    )


if __name__ == "__main__":
    typer.run(main)
