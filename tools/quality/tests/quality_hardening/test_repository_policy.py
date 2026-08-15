from tools.quality.tests.quality_hardening.reporting import scenario_title
from tools.quality.tests.quality_hardening.repository_scenarios import (
    verify_repository_doctor_and_facade,
    verify_repository_secret_and_index_boundaries,
    verify_repository_structure_and_title,
)
from tools.quality.tests.quality_hardening.scenario_catalog import (
    QH_N07,
    QH_N08,
    QH_N09,
)
from tools.quality.tests.quality_hardening.support import QualityWorkspace


@scenario_title(QH_N07)
def test_repository_structure_and_title(quality_workspace: QualityWorkspace) -> None:
    verify_repository_structure_and_title(quality_workspace)


@scenario_title(QH_N08)
def test_repository_secret_and_index_boundaries(
    quality_workspace: QualityWorkspace,
) -> None:
    verify_repository_secret_and_index_boundaries(quality_workspace)


@scenario_title(QH_N09)
def test_repository_doctor_and_facade(quality_workspace: QualityWorkspace) -> None:
    verify_repository_doctor_and_facade(quality_workspace)
