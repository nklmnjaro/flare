import os
from pathlib import Path

import allure
import pytest

from tools.quality.tests.project_state.runtime_evidence import (
    record_runtime_observation,
)
from tools.quality.tests.project_state.support import RepositoryFixture

_RESULTS_ENVIRONMENT_VARIABLE = "FLARE_ALLURE_RESULTS"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del session, exitstatus
    results_dir = os.environ.get(_RESULTS_ENVIRONMENT_VARIABLE)
    if results_dir is not None:
        record_runtime_observation(Path(results_dir))


@pytest.fixture
@allure.title("Create isolated coordination Git repository")
def repository(tmp_path: Path) -> RepositoryFixture:
    return RepositoryFixture(tmp_path / "repo")
