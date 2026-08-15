import pytest

from tools.quality.tests.quality_hardening.reporting import scenario_title
from tools.quality.tests.quality_hardening.reporting_scenarios import (
    verify_sync_and_async_reporting,
)
from tools.quality.tests.quality_hardening.scenario_catalog import QH_N12


@scenario_title(QH_N12)
def test_sync_and_async_reporting(monkeypatch: pytest.MonkeyPatch) -> None:
    verify_sync_and_async_reporting(monkeypatch)
