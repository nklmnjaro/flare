from pathlib import Path

import pytest

from tools.quality.tests.quality_hardening.reporting import fixture_title
from tools.quality.tests.quality_hardening.support import QualityWorkspace


@pytest.fixture
@fixture_title("Подготовить изолированную рабочую область Quality Hardening")
def quality_workspace(tmp_path: Path) -> QualityWorkspace:
    return QualityWorkspace(tmp_path)
