from __future__ import annotations

import argparse
import stat
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from tools.quality.tests.quality_hardening.reporting import ScenarioMetadata
from tools.quality.tests.quality_hardening.scenario_catalog import QUALITY_SCENARIOS


class AllureModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class AllureLabel(AllureModel):
    name: str
    value: str


class AllureAttachment(AllureModel):
    name: str
    source: str


class AllureStep(AllureModel):
    name: str
    status: str | None = None
    steps: tuple[AllureStep, ...] = ()
    attachments: tuple[AllureAttachment, ...] = ()


class AllureResult(AllureModel):
    uuid: str
    name: str
    status: str
    labels: tuple[AllureLabel, ...] = ()
    steps: tuple[AllureStep, ...] = ()
    attachments: tuple[AllureAttachment, ...] = ()


class AllureFixture(AllureModel):
    name: str
    status: str | None = None
    steps: tuple[AllureStep, ...] = ()
    attachments: tuple[AllureAttachment, ...] = ()


class AllureContainer(AllureModel):
    uuid: str
    children: tuple[str, ...] = ()
    befores: tuple[AllureFixture, ...] = ()
    afters: tuple[AllureFixture, ...] = ()


@dataclass(frozen=True, slots=True)
class AllureEvidence:
    results: tuple[AllureResult, ...]
    containers: tuple[AllureContainer, ...]


def _scenario_ids(result: AllureResult) -> tuple[str, ...]:
    return tuple(label.value for label in result.labels if label.name == "scenario_id")


def _label_values(result: AllureResult, name: str) -> tuple[str, ...]:
    return tuple(label.value for label in result.labels if label.name == name)


def _all_steps(steps: tuple[AllureStep, ...]) -> tuple[AllureStep, ...]:
    flattened: list[AllureStep] = []
    pending = list(steps)
    while pending:
        current = pending.pop()
        flattened.append(current)
        pending.extend(current.steps)
    return tuple(flattened)


def _result_errors(
    result: AllureResult,
    metadata: ScenarioMetadata,
) -> tuple[str, ...]:
    errors: list[str] = []
    expected_name = f"[{metadata.scenario_id}] {metadata.title}"
    if result.name != expected_name:
        errors.append(f"{metadata.scenario_id}: неверный русскоязычный заголовок")
    expected_labels = (
        ("parentSuite", "Инженерные контракты Flare"),
        ("suite", "Укрепление качества"),
        ("feature", metadata.feature),
    )
    for label_name, expected_value in expected_labels:
        actual_values = _label_values(result, label_name)
        if actual_values != (expected_value,):
            errors.append(
                f"{metadata.scenario_id}: метка {label_name} ожидалась "
                f"{expected_value!r}, получено {actual_values!r}"
            )
    if result.status != "passed":
        errors.append(f"{metadata.scenario_id}: статус результата {result.status}")
    steps = _all_steps(result.steps)
    if not any(item.name == metadata.title for item in steps):
        errors.append(f"{metadata.scenario_id}: отсутствует шаг сценария")
    if not any("ожидалось" in item.name and "получено" in item.name for item in steps):
        errors.append(f"{metadata.scenario_id}: отсутствует шаг ожидание/результат")
    return tuple(errors)


def _container_errors(container: AllureContainer) -> tuple[str, ...]:
    errors: list[str] = []
    for fixture_kind, fixtures in (
        ("before", container.befores),
        ("after", container.afters),
    ):
        for fixture in fixtures:
            attachment_count = len(fixture.attachments) + sum(
                len(item.attachments) for item in _all_steps(fixture.steps)
            )
            if attachment_count:
                errors.append(
                    f"контейнер {container.uuid!r}: найдено лишнее вложение "
                    f"fixture {fixture_kind} {fixture.name!r}"
                )
    return tuple(errors)


def _duplicate_uuid_errors(
    uuids: tuple[str, ...],
    *,
    kind: str,
) -> tuple[str, ...]:
    counts = Counter(uuids)
    return tuple(
        f"{kind}: UUID {uuid!r} встречается {counts[uuid]} раза"
        for uuid in sorted(counts)
        if uuid and counts[uuid] > 1
    )


def audit_evidence(evidence: AllureEvidence) -> tuple[str, ...]:
    errors: list[str] = []
    result_uuids = tuple(result.uuid for result in evidence.results)
    container_uuids = tuple(container.uuid for container in evidence.containers)
    for result in evidence.results:
        if not result.uuid.strip():
            errors.append(f"результат {result.name!r}: пустой UUID")
        attachment_count = len(result.attachments) + sum(
            len(item.attachments) for item in _all_steps(result.steps)
        )
        if attachment_count:
            errors.append(f"результат {result.uuid!r}: найдено лишнее вложение")
    for container in evidence.containers:
        if not container.uuid.strip():
            errors.append("контейнер Allure: пустой UUID")
    errors.extend(_duplicate_uuid_errors(result_uuids, kind="результаты Allure"))
    errors.extend(_duplicate_uuid_errors(container_uuids, kind="контейнеры Allure"))

    known_results = frozenset(result_uuids)
    for container in evidence.containers:
        for child_uuid in container.children:
            if child_uuid not in known_results:
                errors.append(
                    f"контейнер {container.uuid!r}: неизвестный дочерний "
                    f"UUID {child_uuid!r}"
                )
        errors.extend(_container_errors(container))
    return tuple(errors)


def audit_results(
    results: tuple[AllureResult, ...],
    scenarios: tuple[ScenarioMetadata, ...],
) -> tuple[str, ...]:
    errors: list[str] = []
    valid_ids = frozenset(item.scenario_id for item in scenarios)
    for result in results:
        ids = _scenario_ids(result)
        if len(ids) != 1:
            errors.append(f"результат {result.name!r}: ожидался ровно один scenario_id")
        elif ids[0] not in valid_ids:
            errors.append(
                f"результат {result.name!r}: неизвестный scenario_id {ids[0]}"
            )
    for metadata in scenarios:
        matches = tuple(
            result
            for result in results
            if _scenario_ids(result) == (metadata.scenario_id,)
        )
        if len(matches) != 1:
            errors.append(
                f"{metadata.scenario_id}: ожидался один результат, "
                f"получено {len(matches)}"
            )
        else:
            errors.extend(_result_errors(matches[0], metadata))
    return tuple(errors)


def _entry_kind(mode: int) -> str:
    if stat.S_ISLNK(mode):
        return "символическая ссылка"
    if stat.S_ISDIR(mode):
        return "каталог"
    return "нерегулярный файл"


def load_evidence(directory: Path) -> tuple[AllureEvidence, tuple[str, ...]]:
    results: list[AllureResult] = []
    containers: list[AllureContainer] = []
    errors: list[str] = []
    try:
        directory_mode = directory.lstat().st_mode
    except OSError:
        return AllureEvidence((), ()), ("каталог raw evidence Allure недоступен",)
    if not stat.S_ISDIR(directory_mode) or stat.S_ISLNK(directory_mode):
        return AllureEvidence((), ()), (
            "путь raw evidence Allure не является обычным каталогом",
        )
    try:
        entries = tuple(sorted(directory.iterdir(), key=lambda entry: entry.name))
    except OSError:
        return AllureEvidence((), ()), ("каталог raw evidence Allure недоступен",)

    for path in entries:
        try:
            mode = path.lstat().st_mode
        except OSError:
            errors.append(f"не удалось проверить raw entry Allure {path.name!r}")
            continue
        if not stat.S_ISREG(mode):
            errors.append(
                f"raw entry Allure {path.name!r}: запрещённый тип ({_entry_kind(mode)})"
            )
            continue

        try:
            raw_json = path.read_bytes()
        except OSError:
            errors.append(f"не удалось прочитать raw-файл Allure {path.name!r}")
            continue

        if path.name.endswith("-result.json"):
            try:
                results.append(AllureResult.model_validate_json(raw_json))
            except ValidationError:
                errors.append(f"некорректный результат Allure {path.name!r}")
        elif path.name.endswith("-container.json"):
            try:
                containers.append(AllureContainer.model_validate_json(raw_json))
            except ValidationError:
                errors.append(f"некорректный контейнер Allure {path.name!r}")
        else:
            errors.append(f"лишний raw-файл Allure {path.name!r}")
    return AllureEvidence(tuple(results), tuple(containers)), tuple(errors)


def audit_directory(
    directory: Path,
    scenarios: tuple[ScenarioMetadata, ...],
) -> tuple[str, ...]:
    evidence, load_errors = load_evidence(directory)
    return (
        *load_errors,
        *audit_evidence(evidence),
        *audit_results(evidence.results, scenarios),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    errors = audit_directory(args.results, QUALITY_SCENARIOS)
    if errors:
        print("АУДИТ QUALITY ALLURE: ОШИБКА")
        for finding in errors:
            print(f"- {finding}")
        return 1
    print("АУДИТ QUALITY ALLURE: УСПЕХ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
