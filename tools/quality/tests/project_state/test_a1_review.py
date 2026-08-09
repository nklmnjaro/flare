import allure
import pytest

from tools.quality.tests.project_state.reporting import CHANGE_CONTRACT_URL, Scenario
from tools.quality.tests.project_state.review_scenarios import REVIEW_SCENARIOS


@pytest.mark.parametrize(
    "scenario",
    REVIEW_SCENARIOS,
    ids=[scenario.pytest_id for scenario in REVIEW_SCENARIOS],
)
@allure.parent_suite("Flare contract verification")
@allure.suite("A.1 Coordination State")
@allure.epic("Flare engineering contracts")
@allure.feature("A.1 Coordination State")
@allure.tag("a1", "contract")
@allure.link(CHANGE_CONTRACT_URL, name="A.1 Change contract @ f7db10c")
@allure.title("{param_id}")
def test_a1_review_scenario(scenario: Scenario[None]) -> None:
    scenario.run(None)
