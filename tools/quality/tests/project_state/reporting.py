import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum

import allure

from tools.project_state.model import JSONValue

MAX_ATTACHMENT_BYTES = 16_384
_ATTACHMENT_EDGE_BYTES = 6_000
CHANGE_CONTRACT_URL = (
    "https://github.com/nklmnjaro/flare/blob/"
    "f7db10c0301a5693fdcce1e945040672188a2343/"
    "docs/engineering/changes/FLARE-TRACK-A1-COORDINATION-STATE-001.md"
)


class Area(StrEnum):
    CONCURRENCY = "Concurrency and CAS"
    EVIDENCE = "Test evidence integrity"
    PROJECTION = "Projection"
    PUBLICATION = "Publication"
    REFERENCE = "Reference integrity"
    REVIEW = "Review target identity"
    VALIDATION = "Validation"


@dataclass(frozen=True, slots=True)
class Scenario[T]:
    scenario_id: str
    title: str
    area: Area
    verify: Callable[[T], None]

    @property
    def pytest_id(self) -> str:
        return f"[{self.scenario_id}] {self.title}"

    def __repr__(self) -> str:
        return self.pytest_id

    def run(self, subject: T) -> None:
        environment = "pure-model" if subject is None else "isolated-git"
        allure.dynamic.label("scenario_id", self.scenario_id)
        allure.dynamic.label("test_environment", environment)
        allure.dynamic.sub_suite(self.area.value)
        allure.dynamic.story(self.area.value)
        allure.dynamic.tag(self.area.name.lower(), environment)
        with step_context(self.title):
            self.verify(subject)


def step_context(title: str) -> AbstractContextManager[None]:
    return allure.step(title)


def attach_text(name: str, value: str) -> None:
    if value:
        encoded = value.encode("utf-8")
        if len(encoded) > MAX_ATTACHMENT_BYTES:
            omitted = len(encoded) - (2 * _ATTACHMENT_EDGE_BYTES)
            head = encoded[:_ATTACHMENT_EDGE_BYTES].decode("utf-8", "replace")
            tail = encoded[-_ATTACHMENT_EDGE_BYTES:].decode("utf-8", "replace")
            value = f"{head}\n...[TRUNCATED {omitted} BYTES]...\n{tail}"
        allure.attach(value, name=name, attachment_type="text/plain", extension="txt")


def attach_json(name: str, value: JSONValue) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    encoded = rendered.encode("utf-8")
    if len(encoded) > MAX_ATTACHMENT_BYTES:
        edge = MAX_ATTACHMENT_BYTES // 8
        value = {
            "head": encoded[:edge].decode("utf-8", "replace"),
            "original_bytes": len(encoded),
            "tail": encoded[-edge:].decode("utf-8", "replace"),
            "truncated": True,
        }
        rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    allure.attach(
        rendered,
        name=name,
        attachment_type="application/json",
        extension="json",
    )
