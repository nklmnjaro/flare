from __future__ import annotations

import os
from pathlib import Path

from tools.quality.tests.quality_hardening.allure_audit import (
    AllureAttachment,
    AllureContainer,
    AllureEvidence,
    AllureFixture,
    AllureLabel,
    AllureResult,
    AllureStep,
    audit_directory,
    audit_evidence,
    audit_results,
)
from tools.quality.tests.quality_hardening.assertions import (
    check_contains,
    check_equal,
)
from tools.quality.tests.quality_hardening.reporting import (
    ScenarioMetadata,
    reported,
    step,
)
from tools.quality.tests.quality_hardening.scenario_catalog import QH_N11


def _attachment() -> AllureAttachment:
    return AllureAttachment(name="диагностика", source="unsafe.txt")


def _result(
    metadata: ScenarioMetadata,
    *,
    uuid: str = "result-qh-n11",
    scenario_id: str | None = None,
    name: str | None = None,
    status: str = "passed",
    comparison: bool = True,
    root_attachment: bool = False,
    nested_attachment: bool = False,
) -> AllureResult:
    nested = (
        AllureStep(
            name="Проверка: ожидалось 'успех'; получено 'успех'",
            attachments=(_attachment(),) if nested_attachment else (),
        )
        if comparison
        else AllureStep(name="Проверка без наблюдения")
    )
    return AllureResult(
        uuid=uuid,
        name=name or f"[{metadata.scenario_id}] {metadata.title}",
        status=status,
        labels=(
            AllureLabel(
                name="parentSuite",
                value="Инженерные контракты Flare",
            ),
            AllureLabel(name="suite", value="Укрепление качества"),
            AllureLabel(name="feature", value=metadata.feature),
            AllureLabel(name="scenario_id", value=scenario_id or metadata.scenario_id),
        ),
        steps=(AllureStep(name=metadata.title, status=status, steps=(nested,)),),
        attachments=(_attachment(),) if root_attachment else (),
    )


def _fixture(
    *,
    root_attachment: bool = False,
    nested_attachment: bool = False,
) -> AllureFixture:
    return AllureFixture(
        name="Подготовить изолированную рабочую область",
        status="passed",
        steps=(
            AllureStep(
                name="Подготовить вложенное состояние",
                steps=(
                    AllureStep(
                        name="Проверить глубоко вложенное состояние",
                        attachments=(_attachment(),) if nested_attachment else (),
                    ),
                ),
            ),
        ),
        attachments=(_attachment(),) if root_attachment else (),
    )


def _container(
    uuid: str,
    *,
    child: str = "result-qh-n11",
    before: AllureFixture | None = None,
    after: AllureFixture | None = None,
) -> AllureContainer:
    return AllureContainer(
        uuid=uuid,
        children=(child,),
        befores=(before,) if before is not None else (),
        afters=(after,) if after is not None else (),
    )


def _raw_directory(
    root: Path,
    name: str,
    *,
    results: tuple[AllureResult, ...] = (),
    containers: tuple[AllureContainer, ...] = (),
) -> Path:
    directory = root / name
    directory.mkdir()
    for index, result in enumerate(results):
        (directory / f"{index:02d}-result.json").write_text(
            result.model_dump_json(),
            encoding="utf-8",
        )
    for index, container in enumerate(containers):
        (directory / f"{index:02d}-container.json").write_text(
            container.model_dump_json(),
            encoding="utf-8",
        )
    return directory


def _check_red(directory: Path, expected: str, label: str) -> None:
    errors = audit_directory(directory, (QH_N11,))
    check_contains(expected, "\n".join(errors), label)


def _verify_semantic_result_contract() -> None:
    green = audit_results((_result(QH_N11),), (QH_N11,))
    check_equal(green, (), "нарушения корректного результата Allure")
    red_cases = (
        (
            "дубликат",
            (_result(QH_N11), _result(QH_N11, uuid="result-copy")),
            "ожидался один результат, получено 2",
        ),
        (
            "неизвестный-id",
            (_result(QH_N11, scenario_id="QH-UNKNOWN"),),
            "неизвестный scenario_id",
        ),
        (
            "неверный-заголовок",
            (_result(QH_N11, name="техническая диагностика"),),
            "неверный русскоязычный заголовок",
        ),
        (
            "нет-сравнения",
            (_result(QH_N11, comparison=False),),
            "отсутствует шаг ожидание/результат",
        ),
    )
    for label, results, expected in red_cases:
        with step(f"Отклонить fixture Allure: {label}"):
            errors = audit_results(results, (QH_N11,))
            check_contains(expected, "\n".join(errors), f"нарушение Allure {label}")


def _verify_raw_green(root: Path) -> None:
    unreferenced = _raw_directory(
        root,
        "green-unreferenced",
        results=(_result(QH_N11),),
    )
    check_equal(
        audit_directory(unreferenced, (QH_N11,)),
        (),
        "нарушения raw evidence без контейнера",
    )

    repeated_child = _raw_directory(
        root,
        "green-repeated-child",
        results=(_result(QH_N11),),
        containers=(_container("container-one"), _container("container-two")),
    )
    check_equal(
        audit_directory(repeated_child, (QH_N11,)),
        (),
        "нарушения повторной корректной ссылки контейнеров",
    )


def _verify_raw_identity_red(root: Path) -> None:
    cases = (
        (
            "empty-result-uuid",
            (_result(QH_N11, uuid=""),),
            (),
            "пустой UUID",
        ),
        (
            "duplicate-result-uuid",
            (
                _result(QH_N11),
                _result(QH_N11, uuid="result-qh-n11"),
            ),
            (),
            "UUID 'result-qh-n11' встречается 2 раза",
        ),
        (
            "empty-container-uuid",
            (_result(QH_N11),),
            (_container(""),),
            "контейнер Allure: пустой UUID",
        ),
        (
            "duplicate-container-uuid",
            (_result(QH_N11),),
            (_container("container-one"), _container("container-one")),
            "UUID 'container-one' встречается 2 раза",
        ),
        (
            "unknown-child",
            (_result(QH_N11),),
            (_container("container-one", child="missing-result"),),
            "неизвестный дочерний UUID 'missing-result'",
        ),
    )
    for label, results, containers, expected in cases:
        with step(f"Отклонить нарушение идентичности raw evidence: {label}"):
            directory = _raw_directory(
                root,
                label,
                results=results,
                containers=containers,
            )
            _check_red(directory, expected, f"нарушение идентичности {label}")


def _verify_result_attachment_red(root: Path) -> None:
    cases = (
        ("result-root-attachment", _result(QH_N11, root_attachment=True)),
        ("result-nested-attachment", _result(QH_N11, nested_attachment=True)),
    )
    for label, result in cases:
        with step(f"Отклонить вложение результата Allure: {label}"):
            directory = _raw_directory(root, label, results=(result,))
            _check_red(directory, "найдено лишнее вложение", label)

    unknown = _raw_directory(
        root,
        "unknown-scenario-with-attachment",
        results=(
            _result(
                QH_N11,
                scenario_id="QH-UNKNOWN",
                nested_attachment=True,
            ),
        ),
    )
    errors = "\n".join(audit_directory(unknown, (QH_N11,)))
    check_contains(
        "найдено лишнее вложение",
        errors,
        "generic нарушение вложения неизвестного сценария",
    )
    check_contains(
        "неизвестный scenario_id",
        errors,
        "semantic нарушение идентификатора неизвестного сценария",
    )


def _verify_fixture_attachment_red(root: Path) -> None:
    cases = (
        (
            "before-root-attachment",
            _container("container", before=_fixture(root_attachment=True)),
        ),
        (
            "before-nested-attachment",
            _container("container", before=_fixture(nested_attachment=True)),
        ),
        (
            "after-root-attachment",
            _container("container", after=_fixture(root_attachment=True)),
        ),
        (
            "after-nested-attachment",
            _container("container", after=_fixture(nested_attachment=True)),
        ),
    )
    for label, container in cases:
        with step(f"Отклонить вложение fixture Allure: {label}"):
            directory = _raw_directory(
                root,
                label,
                results=(_result(QH_N11),),
                containers=(container,),
            )
            _check_red(directory, "fixture", f"лишнее вложение fixture {label}")


def _verify_malformed_and_entry_red(root: Path) -> None:
    malformed = _raw_directory(
        root,
        "malformed-json",
        results=(_result(QH_N11),),
    )
    (malformed / "a-container.json").write_text("{", encoding="utf-8")
    (malformed / "b-result.json").write_text("{", encoding="utf-8")
    check_equal(
        audit_directory(malformed, (QH_N11,)),
        (
            "некорректный контейнер Allure 'a-container.json'",
            "некорректный результат Allure 'b-result.json'",
        ),
        "детерминированная агрегация ошибок JSON",
    )

    orphan = _raw_directory(root, "orphan", results=(_result(QH_N11),))
    (orphan / "diagnostics.txt").write_text("лишний файл", encoding="utf-8")
    _check_red(orphan, "лишний raw-файл Allure", "лишний обычный файл")

    symlink = _raw_directory(root, "symlink", results=(_result(QH_N11),))
    target = root / "symlink-target.json"
    target.write_text(_result(QH_N11).model_dump_json(), encoding="utf-8")
    (symlink / "linked-result.json").symlink_to(target)
    _check_red(symlink, "символическая ссылка", "символическая ссылка")

    nested_directory = _raw_directory(
        root,
        "directory-entry",
        results=(_result(QH_N11),),
    )
    (nested_directory / "unexpected").mkdir()
    _check_red(nested_directory, "запрещённый тип (каталог)", "вложенный каталог")

    fifo = _raw_directory(root, "fifo", results=(_result(QH_N11),))
    os.mkfifo(fifo / "stream-result.json")
    _check_red(
        fifo,
        "запрещённый тип (нерегулярный файл)",
        "нерегулярный raw entry",
    )


@reported(QH_N11)
def verify_quality_allure_audit_green_and_red(root: Path) -> None:
    with step("Принять полный типизированный результат Allure"):
        _verify_semantic_result_contract()
    with step("Принять корректную связность raw evidence Allure"):
        _verify_raw_green(root)
    with step("Отклонить неверные UUID raw evidence Allure"):
        _verify_raw_identity_red(root)
    with step("Отклонить вложения результата raw evidence Allure"):
        _verify_result_attachment_red(root)
    with step("Отклонить вложения fixture raw evidence Allure"):
        _verify_fixture_attachment_red(root)
    with step("Отклонить повреждённые и лишние raw entries Allure"):
        _verify_malformed_and_entry_red(root)

    with step("Принять явную модель evidence без обязательной ссылки контейнера"):
        evidence = AllureEvidence((_result(QH_N11),), ())
        check_equal(audit_evidence(evidence), (), "связность без контейнера")
