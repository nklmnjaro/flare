import os
from pathlib import Path

import allure
import pytest

from tools.quality.tests.local_execution.support import (
    LocalExecutionFixture,
    create_fixture,
)
from tools.quality.tests.project_state.runtime_evidence import (
    record_runtime_observation,
)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del session, exitstatus
    results = os.environ.get("FLARE_LOCAL_ALLURE_RESULTS")
    if results is not None:
        record_runtime_observation(Path(results))


@pytest.fixture
@allure.title("Create isolated Local-First repository")
def local_execution_repository(tmp_path: Path) -> LocalExecutionFixture:
    return create_fixture(tmp_path / "repository")
