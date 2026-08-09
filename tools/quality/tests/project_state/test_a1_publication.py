import allure
import pytest

from tools.quality.tests.project_state.publication_scenarios import (
    PUBLICATION_SCENARIOS,
)
from tools.quality.tests.project_state.reporting import CHANGE_CONTRACT_URL, Scenario
from tools.quality.tests.project_state.support import RepositoryFixture


@pytest.mark.parametrize(
    "scenario",
    PUBLICATION_SCENARIOS,
    ids=[scenario.pytest_id for scenario in PUBLICATION_SCENARIOS],
)
@allure.parent_suite("Flare contract verification")
@allure.suite("A.1 Coordination State")
@allure.epic("Flare engineering contracts")
@allure.feature("A.1 Coordination State")
@allure.tag("a1", "contract")
@allure.link(CHANGE_CONTRACT_URL, name="A.1 Change contract @ f7db10c")
@allure.title("{param_id}")
def test_a1_publication_scenario(
    scenario: Scenario[RepositoryFixture],
    repository: RepositoryFixture,
) -> None:
    scenario.run(repository)
