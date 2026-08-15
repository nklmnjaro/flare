from tools.quality.tests.quality_hardening.commit_scenarios import (
    verify_commit_message_green,
    verify_commit_message_red,
)
from tools.quality.tests.quality_hardening.reporting import scenario_title
from tools.quality.tests.quality_hardening.scenario_catalog import QH_N05, QH_N06
from tools.quality.tests.quality_hardening.support import QualityWorkspace


@scenario_title(QH_N05)
def test_commit_message_green(quality_workspace: QualityWorkspace) -> None:
    verify_commit_message_green(quality_workspace)


@scenario_title(QH_N06)
def test_commit_message_red(quality_workspace: QualityWorkspace) -> None:
    verify_commit_message_red(quality_workspace)
