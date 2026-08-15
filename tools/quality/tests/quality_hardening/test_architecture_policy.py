from pathlib import Path

from tools.quality.tests.quality_hardening.allure_scenarios import (
    verify_quality_allure_audit_green_and_red,
)
from tools.quality.tests.quality_hardening.architecture_scenarios import (
    verify_test_architecture_green_and_red,
)
from tools.quality.tests.quality_hardening.reporting import scenario_title
from tools.quality.tests.quality_hardening.scenario_catalog import QH_N10, QH_N11
from tools.quality.tests.quality_hardening.support import QualityWorkspace


@scenario_title(QH_N10)
def test_architecture_green_and_red(quality_workspace: QualityWorkspace) -> None:
    verify_test_architecture_green_and_red(quality_workspace)


@scenario_title(QH_N11)
def test_quality_allure_audit_green_and_red(tmp_path: Path) -> None:
    verify_quality_allure_audit_green_and_red(tmp_path)
